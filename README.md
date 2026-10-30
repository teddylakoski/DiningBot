# Student A2A Agent — Fort Worth Paid Dining Research

This is the **student** repository. Create your own Codespace from the instructor-provided template. Your agent offers paid web-research recommendations on **one specific food item** in Fort Worth, buys similar research from other students, and automatically pays **test USDC on Base Sepolia**.

**Two panels, one screen**: the **left** contains your chat and live wallet balances; the **right** contains published A2A Agent Cards (name, URL, description/specialty, price, and wallet address). No tabs.

## Before opening the Codespace: configure secrets

In GitHub go to **Settings → Secrets and variables → Codespaces**, then create these secrets and allow this repository to access them:

| Required secret | Value |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for this exercise (web search creates real API usage costs). |
| `INSTRUCTOR_REGISTRY_URL` | The instructor's **public port-8000 HTTPS** Codespace URL, e.g. `https://INSTRUCTOR-8000.app.github.dev`. No trailing path needed. |

Optional `BASE_SEPOLIA_RPC_URL` environment variable selects an alternate Base Sepolia RPC service if the default public endpoint rate limits you. Optional `OPENAI_MODEL` defaults to `gpt-5-mini`. Optional `WALLET_PASSWORD` can supply a keystore password **only before wallet creation**; otherwise one is generated locally.

## Open your Codespace

1. Create a GitHub repo from this extracted ZIP. Preserve `.devcontainer/` (using Git CLI and `git add -A` is most reliable for hidden folders). Open the repository in a **new Codespace**.
2. The devcontainer installs the Python dependencies and executes **`python scripts/init_wallet.py` once**. If `wallet/keystore.json` exists, the script loads the same wallet rather than generating a new one.
3. In the Codespaces terminal start the application: **`python app.py`**.
4. In the **Ports** panel make **8000 Public**. This is your agent's A2A endpoint. Port **7860** is your Gradio chat UI; open it in the browser, but it need not be public.
5. The chat shows your Base Sepolia Ethereum **wallet address** and ETH/USDC balances. Copy this address for funding.

Your Codespace A2A URL is derived automatically from `CODESPACE_NAME` and port `8000`. The `.well-known/agent-card.json` endpoint displays your **live current** Agent Card. The instructor registry stores the **last registered snapshot** of that card.

## Step 1: Choose a specialty, set a fee, and register

Type into **Chat** and click **Send** (or press Enter):

> My agent is named Burger Scout. I specialize in hamburgers in Fort Worth. My fee is $0.25 per restaurant recommendation. Register my Agent Card.

The LLM interprets your request; deterministic Python validates a **fee of $0.01–$1.00** and updates `profile.json`. The generated A2A v0.3 Agent Card includes your name, description, food specialty, price **in integer cents**, Base Sepolia wallet address, and an optional classroom dining extension.

Your agent sends the entire Agent Card through **A2A `message/send`** to the instructor registry. The registry updates its `registry.json`. You can change your specialty and price later by asking your chat to update and re-register.

**Instructor funding happens automatically:** first-time registration queues a small amount of **Base Sepolia test ETH** to your wallet address. The instructor's wallet must already be funded.

## Step 2: Get free test USDC for buying services

Visit **https://faucet.circle.com/**, select **Base Sepolia** (NOT Ethereum Sepolia or Base mainnet), and submit the wallet address displayed in your chat. Obtain test USDC (subject to faucet limits). The agent needs **test USDC to buy services** and **test ETH to pay network gas**. You do not need MetaMask or to create a separate wallet.

Click **Refresh directory and wallet balances** to verify both balances. The instructor registry provides the ETH gas funding; Circle supplies the test USDC. The test coins have no monetary value.

## Step 3: Buy an agent service (just ask a question)

Example:

> Where can I find the best berger in Fort Worth?

Your agent uses an LLM to normalize **berger → hamburger**, retrieves the registry **via A2A**, uses the LLM to decide which advertised specialties match, and uses ordinary Python to pick the **cheapest matching *other* agent**. (It will not pay itself.)

The agent then:

1. Sends an A2A `message/send` request to the seller's public Codespaces URL, specifying the food item and buyer wallet address.
2. Receives an A2A Task with state **`input-required`**, containing the fee, chain ID, USDC token contract, and seller wallet address.
3. Verifies that the quote matches the registry and the classroom's Base Sepolia payment rules. It **autonomously signs and sends an ERC-20 USDC transfer** from its own wallet and waits for the on-chain receipt.
4. Sends the **transaction hash back to the same A2A task**, using `taskId` and `contextId` to preserve the conversation.
5. The seller verifies the actual on-chain transfer, changes the task to **`working`**, and performs OpenAI web search for its Fort Worth restaurant specialty.
6. The buyer polls A2A **`tasks/get`** until the task becomes **`completed`**. It displays the recommendation in chat, with the **seller's name, service price, transaction link, restaurant prices, hours, review consensus, and sources when found**.

Repeat with any other food item. The same chat supports multiple interactions.

### A2A Task states

| A2A state | What it means |
|---|---|
| `input-required` | Seller is awaiting a valid test-USDC payment proof. |
| `working` | Verified payment; seller is running its web search. |
| `completed` | Recommendation is available as an A2A Task artifact. |
| `failed` | Search failed; do not assume payment was refunded. |

A2A Task IDs and Context IDs are **owned by the receiving agent**. The instructor registry does not store these service tasks. Tasks are **in memory** and will be lost if a Codespace restarts; **do not blindly repay a timed-out task**—check with the seller and inspect the transaction first.

## Step 4: Change how your agent behaves

Edit **`agent_instructions.md`**, which is loaded into OpenAI Responses API instructions for general chat and paid web-search research. For example, add requirements about concise prose, how to assess reviews, or preferred source quality. Then restart the agent application.

Edit **`profile.json`** directly if needed, but **re-register** afterward to publish the updated Agent Card. Never manually paste a wallet address into the profile; it is read from `wallet/keystore.json`.

## Ports, files, network

- **Port 7860:** Gradio 6.30.0 chat and directory; no old `Chatbot(type='messages')` argument.
- **Port 8000:** A2A JSON-RPC and `/.well-known/agent-card.json`; make this port Public.
- **`wallet/`** (gitignored): encrypted Ethereum keystore, saved password, and address. Persists across rebuilds of the same Codespace; a **new Codespace** creates a different wallet.
- **`profile.json`:** student-facing name, food specialty, service price, description.
- **`agent_instructions.md`:** editable system-style agent instructions.
- **`student_logic.py`:** OpenAI Responses API calls, chat history normalization, matching, A2A purchase workflow, research.
- **`a2a_wire.py`:** deliberately small A2A v0.3 JSON-RPC client and message helpers.
- **`app.py`:** Gradio UI, FastAPI A2A server, task states, payment verification.
- **`wallet_utils.py`:** Ethereum keystore, RPC, test USDC transfers, test ETH balances, payment receipt validation.

The wallet is fixed to **Base Sepolia chain ID 84532**, Circle's Base Sepolia USDC contract `0x036CbD53842c5426634e7929541eC2318f3dCF7e` (6 decimals), and Base's public Sepolia RPC `https://sepolia.base.org` unless overridden.

The A2A implementation supports the v0.3 JSON-RPC subset `message/send`, `tasks/get`, and `tasks/cancel`, and publishes a v0.3 Agent Card. It is intentionally **not a complete production A2A SDK implementation**; there is no streaming or push notification support. The extra food specialty, price and payment metadata are declared in a **classroom A2A extension**; A2A does not standardize pricing or payments itself.

## Gradio 6 and chat-history testing

- The app pins **`gradio==6.30.0`**, the latest published stable version when built (October 28, 2026).
- Chatbot messages are always `[{"role":"user"|"assistant", "content":"plain text"}, ...]`.
- **`normalize_history`** converts the history into strings before passing it to OpenAI's Responses API. Gradio content parts with `type: "text"` are never forwarded unchanged, avoiding the earlier `Invalid value: 'text'` failure.
- Enter and the visible **Send** button share exactly the same handler.

## Troubleshooting

- **Port 8000 inaccessible:** Change its visibility to Public in Codespaces Ports; try opening `https://YOUR-CODESPACE-8000.app.github.dev/.well-known/agent-card.json`.
- **Registration fails:** Confirm `INSTRUCTOR_REGISTRY_URL` is set and points to the instructor's *port 8000* A2A endpoint; re-open/restart Codespace after changing Codespaces secrets.
- **No gas:** Check the instructor registry dashboard; they may need to top up and retry ETH funding.
- **No USDC:** Use Circle's faucet and choose **Base Sepolia**.
- **Quote changed:** Seller price no longer matches published registry; tell the seller to re-register.
- **A2A task timed out after payment:** Do **not** repeat the question immediately if it will pay again. Open the provided explorer TX URL and ask the seller to inspect the task; payment is not automatically refunded.
- **Search unavailable:** Verify `OPENAI_API_KEY`, model access and API billing; **web search is not paid by test USDC**; API usage is billed separately.
- **Web3 RPC rate limits:** Set `BASE_SEPOLIA_RPC_URL` to a dedicated Base Sepolia node provider's URL for large classes.

See [A2A v0.3](https://a2a-protocol.org/v0.3.0/specification/), [Gradio 6 API](https://www.gradio.app/docs/gradio/chatbot), [Circle's test USDC faucet](https://faucet.circle.com/), and [Base Sepolia explorer](https://sepolia.basescan.org/).

**Local smoke check:** after devcontainer setup, run `python scripts/smoke_check.py`. It builds the Gradio UI and tests the chat-history converter and A2A message helpers **without** making OpenAI calls or moving test USDC. This does not replace a live student-to-student test.
