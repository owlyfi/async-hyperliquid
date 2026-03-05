MAINNET_API_URL = "https://api.hyperliquid.xyz"
TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"

USD_FACTOR = 10**6  # USD decimals is 6
HYPE_FACTOR = 10**8  # HYPE decimals is 8

ONE_HOUR_MS = 60 * 60 * 1000

SPOT_OFFSET = 10_000  # SPOT market id starts from 10_000 in Hyperliquid
PERP_DEX_OFFSET = 110_000  # Builder-deployer perp dexs (HIP-3) start at 110_000

SIGNATURE_CHAIN_ID = "0x66eee"

USD_SEND_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "destination", "type": "string"},
    {"name": "amount", "type": "string"},
    {"name": "time", "type": "uint64"},
]

SPOT_TRANSFER_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "destination", "type": "string"},
    {"name": "token", "type": "string"},
    {"name": "amount", "type": "string"},
    {"name": "time", "type": "uint64"},
]

WITHDRAW_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "destination", "type": "string"},
    {"name": "amount", "type": "string"},
    {"name": "time", "type": "uint64"},
]

USD_CLASS_TRANSFER_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "amount", "type": "string"},
    {"name": "toPerp", "type": "bool"},
    {"name": "nonce", "type": "uint64"},
]

SEND_ASSET_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "destination", "type": "string"},
    {"name": "sourceDex", "type": "string"},
    {"name": "destinationDex", "type": "string"},
    {"name": "token", "type": "string"},
    {"name": "amount", "type": "string"},
    {"name": "fromSubAccount", "type": "string"},
    {"name": "nonce", "type": "uint64"},
]

STAKING_TRANSFER_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "wei", "type": "uint64"},
    {"name": "nonce", "type": "uint64"},
]


TOKEN_DELEGATE_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "validator", "type": "address"},
    {"name": "wei", "type": "uint64"},
    {"name": "isUndelegate", "type": "bool"},
    {"name": "nonce", "type": "uint64"},
]

APPROVE_AGENT_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "agentAddress", "type": "address"},
    {"name": "agentName", "type": "string"},
    {"name": "nonce", "type": "uint64"},
]


APPROVE_BUILDER_FEE_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "maxFeeRate", "type": "string"},
    {"name": "builder", "type": "address"},
    {"name": "nonce", "type": "uint64"},
]

CONVERT_TO_MULTI_SIG_USER_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "signers", "type": "string"},
    {"name": "nonce", "type": "uint64"},
]

MULTI_SIG_ENVELOPE_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "multiSigActionHash", "type": "bytes32"},
    {"name": "nonce", "type": "uint64"},
]

USER_DEX_ABSTRACTION_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "user", "type": "address"},
    {"name": "enabled", "type": "bool"},
    {"name": "nonce", "type": "uint64"},
]

USER_SET_ABSTRACTION_SIGN_TYPES = [
    {"name": "hyperliquidChain", "type": "string"},
    {"name": "user", "type": "address"},
    {"name": "abstraction", "type": "string"},
    {"name": "nonce", "type": "uint64"},
]
