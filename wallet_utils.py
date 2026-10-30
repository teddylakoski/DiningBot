"""Base Sepolia keystore, wallet balances, funding transfers and USDC verification.
Classroom code, for testnets ONLY. No mainnet configuration.
"""
from __future__ import annotations
import json
import os
import secrets
import threading
from decimal import Decimal
from pathlib import Path
from eth_account import Account
from web3 import Web3

ROOT = Path(__file__).resolve().parent
WALLET_DIR = ROOT / "wallet"
KEYSTORE_PATH = WALLET_DIR / "keystore.json"
PASSWORD_PATH = WALLET_DIR / ".password"
CHAIN_ID = 84532
RPC_URL = os.getenv("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
USDC = Web3.to_checksum_address("0x036CbD53842c5426634e7929541eC2318f3dCF7e")
USDC_ABI = [
 {"anonymous":False,"inputs":[{"indexed":True,"name":"from","type":"address"},{"indexed":True,"name":"to","type":"address"},{"indexed":False,"name":"value","type":"uint256"}],"name":"Transfer","type":"event"},
 {"inputs":[{"name":"to","type":"address"},{"name":"value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
 {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]
SIGN_LOCK = threading.Lock()


def rpc():
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 25}))
    if w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError(f"Wrong network: expected Base Sepolia chain {CHAIN_ID}")
    return w3


def _password():
    env = os.getenv("WALLET_PASSWORD")
    if env:
        return env
    if not PASSWORD_PATH.exists():
        PASSWORD_PATH.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        PASSWORD_PATH.chmod(0o600)
    return PASSWORD_PATH.read_text(encoding="utf-8").strip()


def initialize_wallet():
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    if KEYSTORE_PATH.exists():
        return local_address()
    account = Account.create()
    pw = _password()
    encrypted = Account.encrypt(account.key, pw)
    KEYSTORE_PATH.write_text(json.dumps(encrypted, indent=2), encoding="utf-8")
    KEYSTORE_PATH.chmod(0o600)
    (WALLET_DIR / "address.txt").write_text(account.address + "\n", encoding="utf-8")
    return account.address


def local_account():
    if not KEYSTORE_PATH.exists():
        raise RuntimeError("Wallet not initialized; run: python scripts/init_wallet.py")
    key = Account.decrypt(json.loads(KEYSTORE_PATH.read_text(encoding="utf-8")), _password())
    return Account.from_key(key)


def local_address():
    if not KEYSTORE_PATH.exists():
        return initialize_wallet()
    return local_account().address


def balances(address=None):
    w3 = rpc()
    addr = Web3.to_checksum_address(address or local_address())
    contract = w3.eth.contract(address=USDC, abi=USDC_ABI)
    eth = w3.eth.get_balance(addr)
    usdc = contract.functions.balanceOf(addr).call()
    return {"address": addr, "eth": str(Web3.from_wei(eth, "ether")), "usdc": str(Decimal(usdc) / Decimal(1_000_000))}


def _broadcast(w3, tx):
    signed = w3.eth.account.sign_transaction(
        tx, private_key=local_account().key
    )
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return Web3.to_hex(tx_hash)

def send_eth(to, amount_eth):
    # This lock serializes nonce assignment for registrations arriving simultaneously.
    with SIGN_LOCK:
        w3 = rpc()
        sender = local_address()
        target = Web3.to_checksum_address(to)
        wei = Web3.to_wei(Decimal(str(amount_eth)), "ether")
        tx = {"from": sender, "to": target, "value": wei,
              "chainId": CHAIN_ID, "nonce": w3.eth.get_transaction_count(sender,"pending"),
              "gas": 21000, "gasPrice": w3.eth.gas_price}
        txhash = _broadcast(w3, tx)
    return txhash


def send_usdc(to, amount):
    units = int(Decimal(str(amount)) * Decimal(1_000_000))
    if units <= 0 or Decimal(str(amount)) * 1_000_000 != units:
        raise ValueError("USDC amount must be positive and have <= 6 decimal places")
    with SIGN_LOCK:
        w3 = rpc()
        sender = local_address()
        contract = w3.eth.contract(address=USDC, abi=USDC_ABI)
        if contract.functions.balanceOf(sender).call() < units:
            raise RuntimeError("Insufficient Base Sepolia test USDC")
        target = Web3.to_checksum_address(to)
        func = contract.functions.transfer(target, units)
        gas = max(75000, int(func.estimate_gas({"from":sender}) * 1.2))
        tx = func.build_transaction({"from": sender, "nonce": w3.eth.get_transaction_count(sender,"pending"),
                                     "chainId":CHAIN_ID, "gas": gas, "gasPrice": w3.eth.gas_price})
        txhash = _broadcast(w3, tx)
    receipt = w3.eth.wait_for_transaction_receipt(txhash, timeout=110)
    if receipt.status != 1:
        raise RuntimeError(f"USDC transfer reverted: {txhash}")
    return txhash


def verify_usdc_payment(txhash, buyer, seller, amount):
    w3 = rpc()
    receipt = w3.eth.get_transaction_receipt(txhash)
    if receipt.status != 1:
        raise ValueError("Payment transaction reverted")
    contract = w3.eth.contract(address=USDC, abi=USDC_ABI)
    required = int(Decimal(str(amount))*Decimal(1_000_000))
    sender = Web3.to_checksum_address(buyer)
    target = Web3.to_checksum_address(seller)
    for entry in receipt.logs:
        if entry.address.lower() != USDC.lower():
            continue
        try:
            decoded = contract.events.Transfer().process_log(entry)
        except Exception:
            continue
        args = decoded["args"]
        if (args["from"] == sender and args["to"] == target and args["value"] == required):
            return True
    raise ValueError("Transaction does not contain the required Base Sepolia USDC transfer")
