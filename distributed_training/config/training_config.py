import os
import torch
import logging

class TrainingConfigClass:
    """
    Cấu hình tập trung cho toàn bộ Pipeline huấn luyện.
    """
    def __init__(self):
        # 1. Nhận diện môi trường
        self.IS_CLOUD = (os.getenv("TRAINING_ENV") == "cloud") or (os.getenv("SPARK_ENV") == "cloud")
    
    @staticmethod
    def _get_env_or_default(key, default):
        return os.getenv(key, default).replace("\\", "/")

    # --- 2. Đường dẫn GCS (Dữ liệu gốc) ---
    @property
    def GCS_BUCKET(self):
        return self._get_env_or_default("GCS_BUCKET", "gs://mining-data-2")
    
    @property
    def GCS_OUTPUT_DIR(self):
        return f"{self.GCS_BUCKET}/output"

    @property
    def GCS_INTERACTIONS(self):
        return f"{self.GCS_OUTPUT_DIR}/all_interactions"

    @property
    def GCS_ITEM_NODES(self):
        return f"{self.GCS_OUTPUT_DIR}/item_nodes"

    @property
    def GCS_PREPARED_DATA(self):
        return f"{self.GCS_OUTPUT_DIR}/prepared_data_improved"

    # --- 3. Đường dẫn Local (Sử dụng ổ cứng tạm SSD của VM) ---
    @property
    def LOCAL_DATA_DIR(self):
        path = "/tmp/training_data" if self.IS_CLOUD else "data/prepared_data_improved"
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def LOCAL_MODELS_DIR(self):
        path = "models_checkpoints"
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def EVAL_PKL_PATH(self):
        return os.path.join(self.LOCAL_DATA_DIR, "evaluation_dataset.pkl")

    @property
    def ITEM_EMBEDDINGS_PATH(self):
        return os.path.join(self.LOCAL_DATA_DIR, "item_embeddings.npy")

    @property
    def ITEM_INDEX_PATH(self):
        return os.path.join(self.LOCAL_DATA_DIR, "item_index.pkl")

    @property
    def VN_CORPUS_PKL_PATH(self):
        return os.path.join(self.LOCAL_DATA_DIR, "vn_corpus.pkl")

    # --- 4. Tham số Distributed (Dành cho 4 GPU) ---
    @property
    def WORLD_SIZE(self):
        return int(os.getenv("WORLD_SIZE", "1"))

    @property
    def RANK(self):
        return int(os.getenv("RANK", "0"))

    @property
    def LOCAL_RANK(self):
        return int(os.getenv("LOCAL_RANK", "0"))

    @property
    def MASTER_ADDR(self):
        return self._get_env_or_default("MASTER_ADDR", "localhost")

    @property
    def MASTER_PORT(self):
        return self._get_env_or_default("MASTER_PORT", "12355")

    @property
    def DEVICE(self):
        if torch.cuda.is_available():
            return torch.device(f"cuda:{self.LOCAL_RANK}")
        return torch.device("cpu")

    # --- 5. Siêu tham số huấn luyện (Đã tối ưu cho 4 GPU) ---
    @property
    def BATCH_SIZE(self):
        return int(self._get_env_or_default("BATCH_SIZE", "128"))

    @property
    def EPOCHS(self):
        return int(self._get_env_or_default("EPOCHS", "3"))

    @property
    def LR(self):
        return float(self._get_env_or_default("LR", "1e-3"))

    @property
    def DATA_FRACTION(self):
        # Giảm xuống 1/8 dữ liệu (12.5%) để chạy siêu tốc
        return float(self._get_env_or_default("DATA_FRACTION", "0.125"))

# Khởi tạo Instance duy nhất
TrainingConfig = TrainingConfigClass()

class RankFilter(logging.Filter):
    def filter(self, record):
        record.rank = TrainingConfig.RANK
        return True

def setup_logging():
    # Chỉ GPU 0 mới in log INFO
    log_level = logging.INFO if TrainingConfig.RANK == 0 else logging.WARNING
    
    # Xóa các handler cũ nếu có
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # Ẩn các cảnh báo phiền phức từ huggingface_hub
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning, module="huggingface_hub")
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [Rank %(rank)s] %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("training_pipeline.log", encoding="utf-8")
        ]
    )
    
    # Thêm RankFilter cho toàn bộ root logger
    for handler in logging.root.handlers:
        handler.addFilter(RankFilter())
