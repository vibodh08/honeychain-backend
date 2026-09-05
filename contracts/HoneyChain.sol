// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract HoneyChain {
    struct HoneyBatch {
        string batchId;
        string metadataHash;
        address registeredBy;
        uint256 timestamp;
    }

    mapping(string => HoneyBatch) private batches;

    event BatchRegistered(
        string batchId,
        string metadataHash,
        address registeredBy,
        uint256 timestamp
    );

    function registerBatch(
        string memory batchId,
        string memory metadataHash
    ) public {
        require(
            bytes(batches[batchId].batchId).length == 0,
            "Batch already registered"
        );

        batches[batchId] = HoneyBatch(
            batchId,
            metadataHash,
            msg.sender,
            block.timestamp
        );

        emit BatchRegistered(
            batchId,
            metadataHash,
            msg.sender,
            block.timestamp
        );
    }

    function verifyBatch(
        string memory batchId
    ) public view returns (
        string memory,
        string memory,
        address,
        uint256
    ) {
        require(
            bytes(batches[batchId].batchId).length != 0,
            "Batch not found"
        );

        HoneyBatch memory batch = batches[batchId];

        return (
            batch.batchId,
            batch.metadataHash,
            batch.registeredBy,
            batch.timestamp
        );
    }
}
