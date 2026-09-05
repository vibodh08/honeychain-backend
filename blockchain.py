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
    """

    private_key = os.getenv("BLOCKCHAIN_PRIVATE_KEY")

    if not private_key:
        raise Exception(
            "BLOCKCHAIN_PRIVATE_KEY environment variable is not set"
        )

    account = w3.eth.account.from_key(private_key)

    nonce = w3.eth.get_transaction_count(
        account.address,
        "pending"
    )

    transaction = contract.functions.registerBatch(
        batch_id,
        metadata_hash
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": 11155111,
        "gas": 200000,
        "gasPrice": w3.eth.gas_price
    })

    signed_transaction = w3.eth.account.sign_transaction(
        transaction,
        private_key=private_key
    )

    tx_hash = w3.eth.send_raw_transaction(
        signed_transaction.raw_transaction
    )

    receipt = w3.eth.wait_for_transaction_receipt(
        tx_hash
    )

    return {
        "tx_hash": tx_hash.hex(),
        "block_number": receipt.blockNumber,
        "registered_by": account.address
    }


# ============================================================
# BLOCKCHAIN VERIFICATION
# ============================================================

def verify_batch_on_blockchain(batch_id: str):
    return contract.functions.verifyBatch(
        batch_id
    ).call()