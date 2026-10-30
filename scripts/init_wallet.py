from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wallet_utils import initialize_wallet
print("Base Sepolia wallet:", initialize_wallet())
