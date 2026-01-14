#!/usr/bin/env python3
"""
ES 데이터 마이그레이션 - 전체 컬럼

PostgreSQL의 5개 테이블 전체 데이터를 Elasticsearch로 마이그레이션합니다.
"""

import asyncio
import asyncpg
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 설정
PG_DSN = "postgresql://postgres:postgres@localhost:5432/ax"
ES_HOST = "http://localhost:9200"
BATCH_SIZE = 5000


def safe_int(value: Any) -> Optional[int]:
    """안전한 정수 변환"""
    if value is None:
        return None
    try:
        v = str(value).replace(",", "").strip()
        if not v:
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


def safe_date(value: Any) -> Optional[str]:
    """날짜를 ES 호환 형식으로 변환"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # yyyyMMdd 형식
        if len(value) == 8 and value.isdigit():
            return value
        # yyyy-MM-dd 형식
        if len(value) >= 10 and "-" in value:
            return value[:10]
    # datetime 객체
    if hasattr(value, 'isoformat'):
        return value.isoformat()[:10]
    return None


# 테이블 설정 - 전체 컬럼 매핑
TABLE_CONFIG = {
    "f_patents": {
        "index": "ax_patents",
        "id_field": "documentid",
        "int_fields": ["id", "claim_cnt", "citation_cnt"],
        "date_fields": ["conts_ymd", "ptnaplc_ymd", "ptnaplc_othbc_ymd", "patent_rgstn_ymd",
                       "created_at", "registration_date", "application_date"],
    },
    "f_projects": {
        "index": "ax_projects",
        "id_field": "conts_id",
        "int_fields": ["id", "tot_rsrh_blgn_amt", "govn_splm_amt", "bnfn_splm_amt",
                      "cmpn_splm_amt", "etc_splm_amt"],
        "date_fields": ["conts_ymd", "rsrh_bgnv_ymd", "rsrh_endv_ymd", "created_at"],
    },
    "f_equipments": {
        "index": "ax_equipments",
        "id_field": "conts_id",
        "int_fields": ["id", "equip_am"],
        "date_fields": ["conts_ymd", "created_at"],
    },
    "f_proposal_profile": {
        "index": "ax_proposals",
        "id_field": "sbjt_id",
        "int_fields": ["id", "dev_period_months"],
        "date_fields": ["tot_dvlp_srt_ymd", "tot_dvlp_end_ymd", "ancm_ymd",
                       "created_at", "start_date", "end_date"],
    },
    "f_ancm_evalp": {
        "index": "ax_evaluations",
        "id_field": "id",  # evalp_id가 없는 경우 id 사용
        "int_fields": ["id", "eval_score_num"],
        "date_fields": ["vlid_srt_ymd", "created_at"],
    }
}


def transform_row(row_dict: Dict, config: Dict) -> Dict:
    """행 데이터를 ES 문서로 변환"""
    doc = {}
    int_fields = set(config.get("int_fields", []))
    date_fields = set(config.get("date_fields", []))

    for key, value in row_dict.items():
        if value is None:
            continue

        # 정수 필드 변환
        if key in int_fields:
            converted = safe_int(value)
            if converted is not None:
                doc[key] = converted
        # 날짜 필드 변환
        elif key in date_fields:
            converted = safe_date(value)
            if converted is not None:
                doc[key] = converted
        # 문자열 필드
        else:
            if isinstance(value, str):
                value = value.strip()
                if value:
                    doc[key] = value
            else:
                doc[key] = value

    return doc


async def migrate_table(table: str, config: Dict, es: Elasticsearch) -> Dict[str, int]:
    """단일 테이블 마이그레이션"""
    index = config["index"]
    id_field = config["id_field"]

    conn = await asyncpg.connect(PG_DSN)

    try:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        logger.info(f"[{table}] Starting: {total:,} rows → {index}")

        migrated = 0
        failed = 0
        offset = 0
        error_samples = []

        while offset < total:
            rows = await conn.fetch(
                f"SELECT * FROM {table} ORDER BY id LIMIT {BATCH_SIZE} OFFSET {offset}"
            )

            if not rows:
                break

            actions = []
            for row in rows:
                try:
                    row_dict = dict(row)
                    doc = transform_row(row_dict, config)

                    # ID 결정
                    doc_id = doc.get(id_field)
                    if not doc_id:
                        doc_id = str(doc.get("id", offset))

                    actions.append({
                        "_index": index,
                        "_id": str(doc_id),
                        "_source": doc,
                    })
                except Exception as e:
                    failed += 1
                    if len(error_samples) < 3:
                        error_samples.append(f"Transform: {e}")

            if actions:
                try:
                    success, errors = bulk(
                        es,
                        actions,
                        raise_on_error=False,
                        raise_on_exception=False,
                    )
                    migrated += success
                    if errors:
                        failed += len(errors)
                        if len(error_samples) < 3:
                            for err in errors[:2]:
                                error_samples.append(str(err)[:150])
                except Exception as e:
                    logger.error(f"Bulk error: {e}")
                    failed += len(actions)

            offset += BATCH_SIZE

            # 진행률 로깅
            if total > 0:
                pct = int((offset / total) * 100)
                if pct % 10 == 0 and offset > 0:
                    logger.info(f"[{table}] {min(pct, 100)}% ({migrated:,} indexed)")

        if error_samples:
            logger.warning(f"[{table}] Errors: {error_samples[:2]}")

        logger.info(f"[{table}] Done: {migrated:,}/{total:,} ({failed} failed)")
        return {"migrated": migrated, "total": total, "failed": failed}

    finally:
        await conn.close()


async def main():
    logger.info("=" * 60)
    logger.info("PostgreSQL → Elasticsearch Full Migration")
    logger.info("=" * 60)

    es = Elasticsearch([ES_HOST])

    if not es.ping():
        logger.error("Cannot connect to Elasticsearch")
        return

    logger.info(f"Connected to ES: {ES_HOST}")

    start_time = datetime.now()
    results = {}

    for table, config in TABLE_CONFIG.items():
        try:
            result = await migrate_table(table, config, es)
            results[table] = result
        except Exception as e:
            logger.error(f"[{table}] Failed: {e}")
            results[table] = {"migrated": 0, "total": 0, "failed": 1, "error": str(e)}

    elapsed = (datetime.now() - start_time).total_seconds()

    # 요약
    logger.info("=" * 60)
    logger.info("Migration Summary")
    logger.info("=" * 60)

    total_migrated = 0
    total_docs = 0

    for table, result in results.items():
        index = TABLE_CONFIG[table]["index"]
        migrated = result.get("migrated", 0)
        total = result.get("total", 0)
        failed = result.get("failed", 0)

        total_migrated += migrated
        total_docs += total

        status = "OK" if failed == 0 else f"WARN ({failed})"
        logger.info(f"  {table:25} → {index:20}: {migrated:>10,}/{total:>10,} {status}")

    logger.info("-" * 60)
    logger.info(f"  Total: {total_migrated:,}/{total_docs:,} in {elapsed:.1f}s")
    logger.info("=" * 60)

    # ES 상태
    logger.info("\nES Index Status:")
    for index in ["ax_patents", "ax_projects", "ax_equipments", "ax_proposals", "ax_evaluations"]:
        try:
            stats = es.indices.stats(index=index)
            doc_count = stats["indices"][index]["primaries"]["docs"]["count"]
            size_mb = stats["indices"][index]["primaries"]["store"]["size_in_bytes"] / (1024 * 1024)
            logger.info(f"  {index}: {doc_count:,} docs, {size_mb:.1f} MB")
        except Exception as e:
            logger.error(f"  {index}: Error - {e}")


if __name__ == "__main__":
    asyncio.run(main())
