import logging
from collections import defaultdict

import util
from block import BlockBuilder, Block
from protos import request_pb2, chain_pb2


class Chain:
    """
    The chain for storing the blocks that make up the block chain and ensuring that no blocks invalidate the chain.
    """

    def get_cost(self):
        """
        Get the total cost of all the blocks in the chain. This can be used to identify how much work has been
        put in to the chain to determine which chain nodes should be working on.
        :return: The cost of all blocks in the chain combined.
        """
        return self.__cost

    @classmethod
    def decode(cls, data, has_bodies):
        """
        Decode a chain from an encoded Chain protocol buffer.
        :param data: The encoded chain.
        :param has_bodies: True if the encoded chain's blocks have their body data; otherwise, False.
        :return: The decoded chain.
        :except: If decoding fails then a DecodeError is thrown.
        """

        chain_data = chain_pb2.Chain()
        chain_data.ParseFromString(data)

        chain = cls()
        for block_data in chain_data.blocks[1:]:
            block = Block.decode(block_data, has_bodies)
            chain.add(block)

        return chain

    def __init__(self):

        # the dictionary of mined blobs to allow a blob to be looked up using its hash to find which block it is in
        self.mined_blobs = defaultdict(set)

        self.blocks = []
        genesis = Block.genesis()
        self.blocks.append(genesis)

        self.__cost = genesis.get_cost()

    def add(self, block):
        """
        Add a block to the chain.
        :param block: The block to be added.
        :return: None
        """
        debug_msg = "Add block to chain with nonce: %d blobs:" % block.get_nonce()
        util.log_collection(logging.DEBUG, debug_msg, block.get_body().blobs)

        block_idx = len(self.blocks)
        self.__add_mined_blobs(block_idx, block)
        self.__cost += block.get_cost()
        self.blocks.append(block)

    def insert(self, idx, block):
        """
        Insert a block into the chain at the specified index.
        :param idx: The index to insert the block at.
        :param block: The block to be inserted
        :return: None
        """

        self.__add_mined_blobs(idx, block)
        self.__cost += block.get_cost()
        self.blocks.insert(idx, block)

    def replace(self, idx, block):
        """
        Replace the block at the provided index with the provided block. This will only update the body of the the
        block at the provided index rather than replacing it because the provided block must have the same header
        to avoid invalidating the chain. This is used during chain resolution to add block binary data for blocks
        that are missing it.
        :param idx: The index of the block to have its body replaced.
        :param block: The block who's body should be used to replace it.
        :return: True if the block's body was replaced with the provided block; otherwise, False.
        """

        if idx <= 0 or idx >= len(self.blocks):
            return False

        cur = self.blocks[idx]
        if cur != block:
            return False

        cur.set_body(block.get_body())
        self.__add_mined_blobs(idx, cur)
        return True

    def __add_mined_blobs(self, block_idx, block):
        """
        Add all binary data stored in the provided block's body to the mined blobs dictionary for lookup.
        :param block_idx: The index of the block in the chain.
        :param block: The block that should have it's block body data added to the mined blobs dictionary.
        :return: None
        """

        if not block.has_body():
            return

        for idx, blob in enumerate(block.get_body().blobs):
            msg = request_pb2.BlobMessage()
            msg.ParseFromString(blob)
            self.mined_blobs[hash(msg.blob)].add((block_idx, idx))

    def next(self, difficulty, blobs):
        """
        Build the next block to try to add to the chain.
        :param difficulty: The difficulty required for the next block to be mined.
        :param blobs: The blobs to be added to the body of the next block.
        :return: None
        """
        prev = self.blocks[-1]
        builder = BlockBuilder(prev.hash(), difficulty)

        debug_msg = "Building block: %d blobs:" % len(blobs)
        util.log_collection(logging.DEBUG, debug_msg, blobs)

        for blob in blobs:
            builder.add(blob)

        return builder.build()

    def is_valid(self):
        """
        Tests whether the chain is valid by computing and verifying the chain of hashes.
        :return: True if the chain is valid; otherwise, False
        """
        if not self.blocks[0].is_valid():
            logging.error("Invalid genesis block: The genesis nonce requires updating.")
            return False
        for i in range(1, len(self.blocks)):
            cur = self.blocks[i]
            prev = self.blocks[i - 1]
            if cur.prev_hash != prev.hash() or not cur.is_valid():
                return False
        return True

    def encode(self, include_body=True):
        """
       Encode the chain into a binary representation that can be sent across the network
       :param include_body: Indicate whether to encode the data in the blocks' bodies
       :return: The binary encoded chain.
       """
        chain = chain_pb2.Chain()
        for block in self.blocks:
            chain.blocks.append(block.encode(include_body))
        return chain.SerializeToString()

    def get_bodiless_indices(self):
        """
        Gets the list of all blocks in the chain that only have a header. The blocks at
        these indices are missing the binary data for their body.
        :return: A list of the indices of blocks that are missing their binary body data.
        """
        indices = []
        for idx, block in enumerate(self.blocks):
            if not block.has_body():
                indices.append(idx)
        return indices

    def is_complete(self):
        """
        Determine if all blocks in the chain have their binary body data meaning that there are no bodiless blocks.
        :return: True if all blocks have their binary body data; otherwise, False.
        """
        if not self.is_valid():
            return False
        for block in self.blocks:
            if not block.has_body():
                return False
        return True
