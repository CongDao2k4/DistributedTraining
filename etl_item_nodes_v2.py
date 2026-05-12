# ============================================================
# src/etl_item_nodes_v2.py (OPTIMIZED VERSION)
# Standardizes Amazon and VN metadata into a common schema.
# ============================================================

import os
import json
import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, concat_ws, lit, lower, regexp_replace, udf, when, coalesce, array_join, trim, from_json
from pyspark.sql.types import StructType, StructField, StringType, ArrayType, MapType
from src.file_utils import detect_jsonl_type, list_files

logger = logging.getLogger("etl_item_nodes_v2")

# --- ĐỊNH NGHĨA SCHEMA CHUẨN (Dựa trên sample_metadatas) ---
VN_ITEM_SCHEMA = StructType([
    StructField("product_id", StringType(), True),
    StructField("asin", StringType(), True),
    StructField("product_name", StringType(), True),
    StructField("specifications", ArrayType(StringType()), True), # Là Array trong mẫu VN
    StructField("description", StringType(), True),
    StructField("breadcrumb", StringType(), True)
])

AMZ_ITEM_SCHEMA = StructType([
    StructField("parent_asin", StringType(), True),
    StructField("asin", StringType(), True),
    StructField("title", StringType(), True),
    StructField("features", ArrayType(StringType()), True),    # Là Array trong mẫu Amz
    StructField("description", ArrayType(StringType()), True), # Là Array trong mẫu Amz
    StructField("main_category", StringType(), True),
    StructField("details", MapType(StringType(), StringType()), True) # Là Map trong mẫu Amz
])

def safe_col(df, col_name, default_val=None):
    if col_name in df.columns:
        return col(col_name)
    else:
        return lit(default_val)

def spark_standardize(c):
    # Xử lý nếu là mảng thì gộp lại, nếu là string thì giữ nguyên
    c = coalesce(concat_ws(" ", c), c.cast("string"), lit(""))
    c = regexp_replace(c, r"\s+", " ")
    return lower(trim(c))

def spark_clean_text(c):
    # Xử lý mảng sang chuỗi trước khi dùng regexp
    c = coalesce(concat_ws(" ", c), c.cast("string"), lit(""))
    c = regexp_replace(c, r"<[^>]*>", " ")
    c = regexp_replace(c, r"[^a-zA-Z0-9\s.,!?àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]", " ")
    c = regexp_replace(c, r"\s+", " ")
    return lower(trim(c))

def get_category_expr(breadcrumb_col, product_name_col):
    text = lower(concat_ws(" ", breadcrumb_col, product_name_col))
    return when(text.rlike("laptop|macbook|máy tính xách tay"), "laptop") \
          .when(text.rlike("điện thoại|smartphone|iphone|dtdd"), "smartphone") \
          .when(text.rlike("tivi|tv|television"), "television") \
          .when(text.rlike("tai nghe|headphone|earphone|airpods"), "headphone") \
          .when(text.rlike("màn hình|monitor"), "monitor") \
          .when(text.rlike("để bàn|desktop|pc|máy tính bộ"), "desktop") \
          .when(text.rlike("tablet|máy tính bảng|ipad"), "tablet") \
          .otherwise("other")

def run_etl_item_nodes(spark, data_dir, output_dir, file_groups: dict = None):
    # QUAN TRỌNG: Cấu hình Spark linh hoạt
    spark.conf.set("spark.sql.caseSensitive", "false")
    
    logger.info(f"[V2-OPTIMIZED] Dang xu ly ETL Item Nodes (Strict .JSONL Mode)...")
    
    if file_groups:
        vn_files = file_groups.get("vn_item", [])
        amz_files = file_groups.get("amz_item", [])
    else:
        all_files = list_files(data_dir)
        # Chỉ quét file .jsonl như yêu cầu
        vn_files = [f for f in all_files if f.endswith(".jsonl") and detect_jsonl_type(f) == "vn_item"]
        amz_files = [f for f in all_files if f.endswith(".jsonl") and detect_jsonl_type(f) == "amz_item"]

    df_final = None

    # 1. Xử lý VN Metadata
    if vn_files:
        logger.info(f"Dang xu ly {len(vn_files)} file VN metadata")
        # Dùng PERMISSIVE và Schema chuẩn
        df_vn = spark.read.option("mode", "PERMISSIVE") \
                          .schema(VN_ITEM_SCHEMA).json(vn_files)
        
        df_vn_std = df_vn.select(
            col("product_id").alias("raw_pid"),
            col("asin").alias("raw_asin"),
            col("product_name").alias("raw_pname"),
            col("specifications").alias("raw_specs"),
            col("description").alias("raw_desc"),
            col("breadcrumb").alias("raw_bc")
        ).withColumn(
            # QUAN TRỌNG: Với VN, product_id đôi khi chính là mã để khớp (nếu asin trống)
            "final_asin", spark_standardize(coalesce(col("raw_asin"), col("raw_pid")))
        ).withColumn(
            "product_id", spark_standardize(col("raw_pid"))
        ).withColumn(
            "asin", col("final_asin")
        ).withColumn(
            "product_name", spark_standardize(col("raw_pname"))
        ).withColumn(
            "category", get_category_expr(col("raw_bc"), col("raw_pname"))
        ).withColumn(
            "specs_text", spark_clean_text(col("raw_specs"))
        ).withColumn(
            "full_text", concat_ws(" ", col("raw_pname"), col("raw_specs"), col("raw_desc"))
        ).withColumn("domain", lit("vn"))

        df_vn_final = df_vn_std.select("product_id", "asin", "product_name", "category", "full_text", "specs_text", "domain")
        df_final = df_vn_final

    # 2. Xử lý Amazon Metadata
    if amz_files:
        logger.info(f"Dang xu ly {len(amz_files)} file Amazon metadata")
        df_amz = spark.read.option("mode", "PERMISSIVE") \
                          .schema(AMZ_ITEM_SCHEMA).json(amz_files)
        
        df_amz_std = df_amz.select(
            col("parent_asin").alias("raw_p_asin"),
            col("asin").alias("raw_a_asin"),
            col("title").alias("raw_title"),
            col("features").alias("raw_features"),
            col("description").alias("raw_desc"),
            col("details").alias("raw_details"),
            col("main_category").alias("raw_bc")
        ).withColumn(
            # TRÍCH XUẤT ASIN TỪ MAP DETAILS (Nếu có)
            "details_asin", coalesce(col("raw_details")["ASIN"], col("raw_details")["asin"])
        ).withColumn(
            # Ưu tiên: asin > parent_asin > asin trong details
            "final_asin", spark_standardize(coalesce(col("raw_a_asin"), col("raw_p_asin"), col("details_asin")))
        ).withColumn(
            "product_id", when(spark_standardize(col("raw_p_asin")) != "", spark_standardize(col("raw_p_asin")))
                          .otherwise(col("final_asin"))
        ).withColumn(
            "asin", col("final_asin")
        ).withColumn(
            "product_name", spark_standardize(col("raw_title"))
        ).withColumn(
            "category", get_category_expr(col("raw_bc"), col("raw_title"))
        ).withColumn(
            "specs_text", spark_clean_text(coalesce(col("raw_details").cast("string"), col("raw_features").cast("string")))
        ).withColumn(
            "full_text", concat_ws(" ", col("raw_title"), col("specs_text"), col("raw_desc"))
        ).withColumn("domain", lit("amazon"))

        df_amz_final = df_amz_std.select(
            "product_id", "asin", "product_name", "category", "full_text", "specs_text", "domain"
        )
        
        if df_final is None: df_final = df_amz_final
        else: df_final = df_final.unionByName(df_amz_final)

    if df_final is None:
        logger.warning("Khong tim thay file metadata nao!")
        return 0

    # Lọc và Parse JSON Native
    map_schema = "MAP<STRING, STRING>"
    # TỐI ƯU: Không dropDuplicates quá tay chỉ theo product_id (parent_asin) 
    # vì sẽ làm mất các phiên bản con (asin) có thể khớp với VN.
    df_final = df_final.filter(col("product_id") != "").dropDuplicates(["product_id", "asin"]) \
                       .withColumn("parsed_specs", 
                           when(col("specs_text").startswith("{"), from_json(col("specs_text"), map_schema))
                           .otherwise(None)
                       ).drop("specs_text")

    # TỐI ƯU: Ghi trực tiếp
    logger.info(f"Saving to Parquet (V2-Coalesce) -> {output_dir}")
    df_final.coalesce(16).write.mode("overwrite").parquet(output_dir)
    
    # TỐI ƯU: Đếm số lượng từ metadata của file đã ghi (Cực nhanh vì chỉ đọc footer Parquet)
    final_count = spark.read.parquet(output_dir).count()
    return final_count


