import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# SEPOLIA
# ============================================================

SEPOLIA_RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"

w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))

# ============================================================
# CONTRACT
# ============================================================

CONTRACT_ADDRESS = Web3.to_checksum_address(
    "0x8B12321F29947DE607e16218D8A582756E77E61C"
)

CONTRACT_ABI = [
    # registerBatch()
    {
        "inputs": [
            {
                "internalType": "string",
                "name": "batchId",
                "type": "string"
            },
            {
                "internalType": "string",
                "name": "metadataHash",
                "type": "string"
            }
        ],
        "name": "registerBatch",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },

    # verifyBatch()
    {
        "inputs": [
            {
                "internalType": "string",
                "name": "batchId",
                "type": "string"
            }
        ],
        "name": "verifyBatch",
        "outputs": [
            {
                "internalType": "string",
                "name": "",
                "type": "string"
            },
            {
                "internalType": "string",
                "name": "",
                "type": "string"
            },
            {
                "internalType": "address",
                "name": "",
                "type": "address"
            },
            {
                "internalType": "uint256",
                "name": "",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

contract = w3.eth.contract(
    address=CONTRACT_ADDRESS,
    abi=CONTRACT_ABI
)


# ============================================================
# BLOCKCHAIN REGISTRATION
# ============================================================

def register_batch_on_blockchain(
    batch_id: str,
    metadata_hash: str
):
    """
    Register a honey batch on the Sepolia blockchain.

    Uses an EIP-1559 dynamic-fee transaction and returns the
    transaction hash immediately instead of waiting for mining.
    """

    private_key = os.getenv("BLOCKCHAIN_PRIVATE_KEY")

    if not private_key:
        raise Exception(
            "BLOCKCHAIN_PRIVATE_KEY environment variable is not set"
        )

    if not w3.is_connected():
        raise Exception("Unable to connect to Sepolia RPC")

    account = w3.eth.account.from_key(private_key)

    # Include pending transactions when determining the nonce.
    nonce = w3.eth.get_transaction_count(
        account.address,
        "pending"
    )

    # --------------------------------------------------------
    # EIP-1559 fee calculation
    # --------------------------------------------------------

    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas")

    if base_fee is None:
        raise Exception(
            "Sepolia RPC did not return baseFeePerGas"
        )

    # Dynamic fee transaction.
    max_priority_fee = w3.to_wei(2, "gwei")
    max_fee_per_gas = (base_fee * 2) + max_priority_fee

    # --------------------------------------------------------
    # Build transaction
    # --------------------------------------------------------

    transaction = contract.functions.registerBatch(
        batch_id,
        metadata_hash
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": 11155111,
        "gas": 200000,
        "maxPriorityFeePerGas": max_priority_fee,
        "maxFeePerGas": max_fee_per_gas,
        "type": 2
    })

    # --------------------------------------------------------
    # Sign transaction
    # --------------------------------------------------------

    signed_transaction = w3.eth.account.sign_transaction(
        transaction,
        private_key=private_key
    )

    # --------------------------------------------------------
    # Broadcast transaction
    # --------------------------------------------------------

    tx_hash = w3.eth.send_raw_transaction(
        signed_transaction.raw_transaction
    )

    # Do NOT wait for the receipt here.
    # Confirmation can be checked separately.
    return {
        "tx_hash": tx_hash.hex(),
        "block_number": None,
        "registered_by": account.address,
        "status": "Transaction submitted - awaiting confirmation"
    }


# ============================================================
# TRANSACTION STATUS
# ============================================================

def get_transaction_status(tx_hash: str):
    """
    Check whether a submitted transaction has been mined.

    Returns:
        pending -> still waiting for confirmation
        success -> mined successfully
        failed  -> mined but reverted
    """

    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        if receipt is None:
            return {
                "status": "pending",
                "tx_hash": tx_hash,
                "block_number": None
            }

        if receipt.status == 1:
            return {
                "status": "success",
                "tx_hash": tx_hash,
                "block_number": receipt.blockNumber
            }

        return {
            "status": "failed",
            "tx_hash": tx_hash,
            "block_number": receipt.blockNumber
        }

    except Exception:
        # A transaction that has not been mined may cause the RPC
        # to raise an exception instead of returning None.
        return {
            "status": "pending",
            "tx_hash": tx_hash,
            "block_number": None
        }


# ============================================================
# BLOCKCHAIN VERIFICATION
# ============================================================

def verify_batch_on_blockchain(batch_id: str):
    """
    Read a registered honey batch directly from the
    HoneyChain smart contract.
    """

    return contract.functions.verifyBatch(
        batch_id
    ).call()
