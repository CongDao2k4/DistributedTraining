import torch
import pandas as pd
import pyarrow.parquet as pq
from torch.utils.data import Dataset, DataLoader, DistributedSampler
import logging

logger = logging.getLogger("parquet_loader")

class ParquetDataset(Dataset):
    def __init__(self, parquet_path):
        """
        Production-grade Parquet Loader for GCS.
        Uses pyarrow for efficient metadata handling and streaming.
        """
        logger.info(f"Connecting to GCS dataset: {parquet_path}")
        
        # Load metadata only first to be memory efficient
        try:
            # Note: For GCS, pyarrow handles 'gs://' natively if gcsfs is installed
            self.dataset = pq.ParquetDataset(parquet_path, use_legacy_dataset=False)
            self.table = self.dataset.read()
            self.df = self.table.to_pandas()
            logger.info(f"Successfully loaded {len(self.df)} rows from {parquet_path}")
        except Exception as e:
            logger.error(f"Failed to stream from GCS: {e}")
            raise
        
    def __len__(self):
        return len(self.df)
    
    def __getitem__(self, idx):
        # Access data efficiently from the pyarrow-backed dataframe
        row = self.df.iloc[idx]
        return {
            "query_id":      str(row["query_id"]),
            "query_text":    str(row["query_text"]),
            "candidate_ids": list(row["candidate_ids"]),
            "candidate_texts": list(row["candidate_texts"]),
            "labels":        torch.tensor(list(row["labels"]), dtype=torch.long)
        }

def get_dist_dataloader(parquet_path, batch_size, world_size, rank):
    dataset = ParquetDataset(parquet_path)
    sampler = DistributedSampler(dataset, num_replicas=world_size, rank=rank, shuffle=True)
    
    return DataLoader(
        dataset,
        batch_size=batch_size,
        sampler=sampler,
        num_workers=4,        # Parallel data loading
        pin_memory=True,      # Speed up host-to-device transfer
        prefetch_factor=2     # Prefetch batches for GPU
    )
