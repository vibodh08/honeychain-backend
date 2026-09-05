from web3 import Web3

# Sepolia public RPC
SEPOLIA_RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"

# Our deployed HoneyChain contract
CONTRACT_ADDRESS = Web3.to_checksum_address(
    "0x8B12321F29947DE607e16218D8A582756E77E61C"
)

# Minimal ABI for the functions we need
CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "batchId", "type": "string"}
        ],
        "name": "verifyBatch",
        "outputs": [
            {"internalType": "string", "name": "", "type": "string"},
            {"internalType": "string", "name": "", "type": "string"},
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]


w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))

contract = w3.eth.contract(
    address=CONTRACT_ADDRESS,
    abi=CONTRACT_ABI
)


def verify_batch_on_blockchain(batch_id: str):
    return contract.functions.verifyBatch(batch_id).call()