#!/usr/bin/env python3
"""
ES 데이터 마이그레이션 실행 스크립트 v3 - ES 매핑에 정확히 맞춤

PostgreSQL의 4개 테이블 데이터를 Elasticsearch로 마이그레이션합니다.
(ax_patents는 이미 완료됨)
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


def format_date(value: Any) -> Optional[str]:
    """날짜 형식 변환 (yyyyMMdd 또는 yyyy-MM-dd)"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if len(value) == 8 and value.isdigit():
            return value  # yyyyMMdd 그대로 반환 (ES가 파싱함)
        if len(value) >= 10 and "-" in value:
            return value[:10]
    return None


def safe_int(value: Any) -> Optional[int]:
    """안전한 정수 변환"""
    if value is None:
        return None
    try:
        v = str(value).replace(",", "").strip()
        return int(float(v))
    except (ValueError, TypeError):
        return None


def safe_float(value: Any) -> Optional[float]:
    """안전한 실수 변환"""
    if value is None:
        return None
    try:
        v = str(value).replace(",", "").strip()
        return float(v)
    except (ValueError, TypeError):
        return None


# 테이블 → 인덱스 매핑 (ES 매핑에 정확히 맞춤)
# ax_projects 매핑 필드: conts_id, conts_klang_nm, conts_rspns_nm, bucl_nm, ancm_tl_nm, ancm_yy,
#                       conts_ymd, tot_rsrh_blgn_amt, govn_splm_amt, conts_lclas_nm, conts_mclas_nm,
#                       conts_sclas_nm, rsrh_goal, rsrh_summary, created_at, updated_at
TABLE_CONFIG = {
    "f_projects": {
        "index": "ax_projects",
        "id_field": "conts_id",
        "transform": lambda r: {
            "conts_id": r.get("conts_id"),
            "conts_klang_nm": r.get("conts_klang_nm"),
            "conts_rspns_nm": r.get("conts_rspns_nm"),
            "bucl_nm": r.get("bucl_nm"),
            "ancm_tl_nm": r.get("ancm_tl_nm"),
            "ancm_yy": r.get("ancm_yy"),
            "conts_ymd": format_date(r.get("conts_ymd")),
            "tot_rsrh_blgn_amt": safe_int(r.get("tot_rsrh_blgn_amt")),
            "govn_splm_amt": safe_int(r.get("govn_splm_amt")),
            "conts_lclas_nm": r.get("conts_lclas_nm"),
            "conts_mclas_nm": r.get("conts_mclas_nm"),
            "conts_sclas_nm": r.get("conts_sclas_nm"),
        }
    },
    # ax_equipments 매핑 필드: conts_id, conts_klang_nm, org_nm, equip_purpose, equip_spec,
    #                        install_loc, address_dosi, region_code, equip_grp_lv1_nm,
    #                        equip_grp_lv2_nm, equip_grp_lv3_nm, conts_lclas_nm, conts_mclas_nm,
    #                        acqst_ymd, acqst_amt, kpi_nm_list, geo_location, created_at, updated_at
    "f_equipments": {
        "index": "ax_equipments",
        "id_field": "conts_id",
        "transform": lambda r: {
            "conts_id": r.get("conts_id") or r.get("equip_ntis_id"),
            "conts_klang_nm": r.get("conts_klang_nm"),
            "org_nm": r.get("org_nm") or r.get("equip_org_nm"),
            "equip_purpose": r.get("equip_desc"),
            "equip_spec": r.get("equip_spec"),
            "install_loc": r.get("org_addr"),
            "address_dosi": r.get("address_dosi"),
            "region_code": r.get("region_code"),
            "equip_grp_lv1_nm": r.get("equip_grp_lv1_nm"),
            "equip_grp_lv2_nm": r.get("equip_grp_lv2_nm"),
            "equip_grp_lv3_nm": r.get("equip_grp_lv3_nm"),
            "conts_lclas_nm": r.get("conts_lclas_nm"),
            "conts_mclas_nm": r.get("conts_mclas_nm"),
            "acqst_amt": safe_int(r.get("equip_am")),
            "kpi_nm_list": r.get("kpi_nm_list"),
        }
    },
    # ax_proposals 매핑 필드: sbjt_id, sbjt_nm, orgn_nm, dvlp_gole, rsrh_cn, expct_efct,
    #                       rsrh_expn, ancm_yy, tecl_cd, tecl_nm, tecl_nm_tree, created_at, updated_at
    "f_proposal_profile": {
        "index": "ax_proposals",
        "id_field": "sbjt_id",
        "transform": lambda r: {
            "sbjt_id": r.get("sbjt_id"),
            "sbjt_nm": r.get("sbjt_nm"),
            "orgn_nm": r.get("orgn_nm"),
            "dvlp_gole": r.get("dvlp_gole"),
            "rsrh_cn": r.get("rhdp_whol_cn"),  # 연구내용
            "expct_efct": r.get("prd_sv_nm"),  # 기대효과/제품서비스명
            "ancm_yy": r.get("ancm_yy"),
        }
    },
    # ax_evaluations - 이전과 동일
    "f_ancm_evalp": {
        "index": "ax_evaluations",
        "id_field": "evalp_id",
        "transform": lambda r: {
            "evalp_id": r.get("evalp_id"),
            "ancm_id": r.get("ancm_id"),
            "ancm_nm": r.get("bucl_nm"),
            "eval_idx_nm": r.get("eval_idx_nm"),
            "eval_score": safe_float(r.get("dmrk_gd")),
            "eval_note": r.get("evalp_nm"),
            "prcnd_se_nm": r.get("evalp_tp_se_nm"),
            "prcnd_cn": r.get("bucl_depth4_nm"),
        }
    }
}


async def migrate_table(table: str, config: Dict, es: Elasticsearch) -> Dict[str, int]:
    """단일 테이블 마이그레이션"""
    index = config["index"]
    id_field = config["id_field"]
    transform = config["transform"]

    conn = await asyncpg.connect(PG_DSN)

    try:
        # 총 행 수 조회
        total = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        logger.info(f"[{table}] Starting migration: {total:,} rows → {index}")

        migrated = 0
        failed = 0
        offset = 0
        error_samples = []

        while offset < total:
            # 배치 조회
            rows = await conn.fetch(
                f"SELECT * FROM {table} ORDER BY id LIMIT {BATCH_SIZE} OFFSET {offset}"
            )

            if not rows:
                break

            # ES 액션 생성
            actions = []
            for row in rows:
                try:
                    row_dict = dict(row)
                    doc = transform(row_dict)

                    # None 값 필드 제거
                    doc = {k: v for k, v in doc.items() if v is not None}

                    doc_id = doc.get(id_field) or str(row_dict.get("id", offset))

                    actions.append({
                        "_index": index,
                        "_id": doc_id,
                        "_source": doc,
                    })
                except Exception as e:
                    failed += 1
                    if len(error_samples) < 3:
                        error_samples.append(f"Transform error: {e}")

            # Bulk 인덱싱
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
                                error_samples.append(str(err)[:200])
                except Exception as e:
                    logger.error(f"Bulk error: {e}")
                    failed += len(actions)

            offset += BATCH_SIZE

            # 진행률 로깅 (20% 단위)
            if total > 0:
                pct = int((offset / total) * 100)
                if pct % 20 == 0 and offset > 0:
                    logger.info(f"[{table}] Progress: {min(pct, 100)}% ({migrated:,} indexed)")

        if error_samples:
            logger.warning(f"[{table}] Error samples: {error_samples[:2]}")

        logger.info(f"[{table}] Completed: {migrated:,}/{total:,} ({failed} failed)")
        return {"migrated": migrated, "total": total, "failed": failed}

    finally:
        await conn.close()


async def main():
    """메인 함수"""
    logger.info("=" * 60)
    logger.info("PostgreSQL → Elasticsearch Migration v3")
    logger.info("=" * 60)

    es = Elasticsearch([ES_HOST])

    # ES 연결 확인
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
            logger.error(f"[{table}] Migration failed: {e}")
            results[table] = {"migrated": 0, "total": 0, "failed": 1, "error": str(e)}

    elapsed = (datetime.now() - start_time).total_seconds()

    # 요약 출력
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

        status = "OK" if failed == 0 else f"WARN ({failed} failed)"
        logger.info(f"  {table:25} → {index:20}: {migrated:>10,}/{total:>10,} {status}")

    logger.info("-" * 60)
    logger.info(f"  Total: {total_migrated:,}/{total_docs:,} documents in {elapsed:.1f}s")
    logger.info("=" * 60)

    # ES 인덱스 상태 확인
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
