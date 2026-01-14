"""
PostgreSQL → Elasticsearch 데이터 마이그레이터

PostgreSQL 테이블 데이터를 Elasticsearch 인덱스로 마이그레이션합니다.
배치 처리 및 진행률 표시를 지원합니다.
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Generator
from datetime import datetime
from dataclasses import dataclass
import asyncpg
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

logger = logging.getLogger(__name__)

# 환경 변수
ES_HOST = os.getenv("ES_HOST", "localhost")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DATABASE = os.getenv("PG_DATABASE", "ax_db")


@dataclass
class MigrationStats:
    """마이그레이션 통계"""
    table: str
    index: str
    total_rows: int
    migrated: int
    failed: int
    elapsed_seconds: float

    @property
    def success_rate(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return (self.migrated / self.total_rows) * 100

    def __str__(self) -> str:
        return (
            f"{self.table} → {self.index}: "
            f"{self.migrated:,}/{self.total_rows:,} "
            f"({self.success_rate:.1f}%) "
            f"in {self.elapsed_seconds:.1f}s"
        )


class ESMigrator:
    """
    PostgreSQL → Elasticsearch 데이터 마이그레이터

    배치 단위로 데이터를 읽어 ES에 인덱싱합니다.

    사용 예:
        migrator = ESMigrator()
        await migrator.migrate_all()
    """

    BATCH_SIZE = 5000

    # 테이블 → 인덱스 매핑
    TABLE_INDEX_MAP = {
        "f_patents": "ax_patents",
        "f_projects": "ax_projects",
        "f_equipments": "ax_equipments",
        "f_proposal_profile": "ax_proposals",
        "f_ancm_evalp": "ax_evaluations",
    }

    # 테이블별 ID 필드
    ID_FIELD_MAP = {
        "f_patents": "documentid",
        "f_projects": "conts_id",
        "f_equipments": "eqp_id",
        "f_proposal_profile": "tecl_id",
        "f_ancm_evalp": "evalp_id",
    }

    # 테이블별 변환 함수
    TRANSFORM_MAP: Dict[str, Callable] = {}

    def __init__(
        self,
        es_hosts: Optional[List[str]] = None,
        pg_dsn: Optional[str] = None,
        batch_size: int = BATCH_SIZE,
    ):
        """
        마이그레이터 초기화

        Args:
            es_hosts: ES 호스트 목록
            pg_dsn: PostgreSQL 연결 문자열
            batch_size: 배치 크기
        """
        self.es_hosts = es_hosts or [f"http://{ES_HOST}:{ES_PORT}"]
        self.pg_dsn = pg_dsn or f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
        self.batch_size = batch_size

        self._es_client: Optional[AsyncElasticsearch] = None
        self._pg_pool: Optional[asyncpg.Pool] = None

    async def _get_es_client(self) -> AsyncElasticsearch:
        """ES 클라이언트 반환"""
        if self._es_client is None:
            self._es_client = AsyncElasticsearch(hosts=self.es_hosts)
        return self._es_client

    async def _get_pg_pool(self) -> asyncpg.Pool:
        """PostgreSQL 커넥션 풀 반환"""
        if self._pg_pool is None:
            self._pg_pool = await asyncpg.create_pool(
                self.pg_dsn,
                min_size=2,
                max_size=10,
            )
        return self._pg_pool

    async def _get_table_count(self, table: str) -> int:
        """테이블 행 수 조회"""
        pool = await self._get_pg_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            return result or 0

    def _transform_patent(self, row: asyncpg.Record) -> Dict[str, Any]:
        """특허 데이터 변환"""
        return {
            "documentid": row.get("documentid"),
            "conts_klang_nm": row.get("conts_klang_nm"),
            "patent_abstc_ko": row.get("patent_abstc_ko"),
            "objectko": row.get("objectko"),
            "solutionko": row.get("solutionko"),
            "patent_frst_appn": row.get("patent_frst_appn"),
            "ipc_main": row.get("ipc_main"),
            "ipc_all": row.get("ipc_all"),
            "ntcd": row.get("ntcd"),
            "patent_frst_appn_ntnlty": row.get("patent_frst_appn_ntnlty"),
            "ptnaplc_ymd": self._format_date(row.get("ptnaplc_ymd")),
            "patent_rgstn_ymd": self._format_date(row.get("patent_rgstn_ymd")),
            "citation_cnt": row.get("citation_cnt"),
            "claim_cnt": row.get("claim_cnt"),
            "status": row.get("status"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _transform_project(self, row: asyncpg.Record) -> Dict[str, Any]:
        """연구과제 데이터 변환"""
        return {
            "conts_id": row.get("conts_id"),
            "conts_klang_nm": row.get("conts_klang_nm"),
            "conts_cn": row.get("conts_cn"),
            "conts_rspns_nm": row.get("conts_rspns_nm"),
            "conts_rsrh_org_nm": row.get("conts_rsrh_org_nm"),
            "conts_rsrh_fld_nm": row.get("conts_rsrh_fld_nm"),
            "tot_rsrh_blgn_amt": row.get("tot_rsrh_blgn_amt"),
            "bgng_ymd": self._format_date(row.get("bgng_ymd")),
            "end_ymd": self._format_date(row.get("end_ymd")),
            "ntsl_code_nm": row.get("ntsl_code_nm"),
            "bsns_nm": row.get("bsns_nm"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _transform_equipment(self, row: asyncpg.Record) -> Dict[str, Any]:
        """장비 데이터 변환"""
        doc = {
            "eqp_id": row.get("eqp_id"),
            "eqp_nm": row.get("eqp_nm"),
            "eqp_cn": row.get("eqp_cn"),
            "eqp_mdl_nm": row.get("eqp_mdl_nm"),
            "org_nm": row.get("org_nm"),
            "org_addr": row.get("org_addr"),
            "eqp_ctgr_nm": row.get("eqp_ctgr_nm"),
            "eqp_prc_amt": row.get("eqp_prc_amt"),
            "open_yn": row.get("open_yn"),
            "fee_yn": row.get("fee_yn"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        # 위치 정보가 있으면 geo_location 추가
        lat = row.get("latitude")
        lon = row.get("longitude")
        if lat is not None and lon is not None:
            doc["geo_location"] = {"lat": float(lat), "lon": float(lon)}

        return doc

    def _transform_proposal(self, row: asyncpg.Record) -> Dict[str, Any]:
        """제안서 데이터 변환"""
        return {
            "tecl_id": row.get("tecl_id"),
            "ancm_id": row.get("ancm_id"),
            "tecl_nm": row.get("tecl_nm"),
            "dvlp_gole": row.get("dvlp_gole"),
            "dvlp_fnsh_gole": row.get("dvlp_fnsh_gole"),
            "expct_efct": row.get("expct_efct"),
            "tech_rn": row.get("tech_rn"),
            "anls_sht": row.get("anls_sht"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _transform_evaluation(self, row: asyncpg.Record) -> Dict[str, Any]:
        """평가표 데이터 변환"""
        return {
            "evalp_id": row.get("evalp_id"),
            "ancm_id": row.get("ancm_id"),
            "ancm_nm": row.get("ancm_nm"),
            "eval_idx_nm": row.get("eval_idx_nm"),
            "eval_score": row.get("eval_score"),
            "eval_note": row.get("eval_note"),
            "prcnd_se_nm": row.get("prcnd_se_nm"),
            "prcnd_cn": row.get("prcnd_cn"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    def _format_date(self, date_value: Any) -> Optional[str]:
        """날짜 형식 변환"""
        if date_value is None:
            return None
        if isinstance(date_value, str):
            # yyyyMMdd → yyyy-MM-dd
            if len(date_value) == 8 and date_value.isdigit():
                return f"{date_value[:4]}-{date_value[4:6]}-{date_value[6:8]}"
            return date_value
        if isinstance(date_value, datetime):
            return date_value.strftime("%Y-%m-%d")
        return str(date_value)

    def _get_transformer(self, table: str) -> Callable:
        """테이블별 변환 함수 반환"""
        transformers = {
            "f_patents": self._transform_patent,
            "f_projects": self._transform_project,
            "f_equipments": self._transform_equipment,
            "f_proposal_profile": self._transform_proposal,
            "f_ancm_evalp": self._transform_evaluation,
        }
        return transformers.get(table, lambda x: dict(x))

    async def _generate_actions(
        self,
        table: str,
        index: str,
    ) -> Generator[Dict[str, Any], None, None]:
        """ES bulk 작업 생성 제너레이터"""
        pool = await self._get_pg_pool()
        transformer = self._get_transformer(table)
        id_field = self.ID_FIELD_MAP.get(table, "id")

        async with pool.acquire() as conn:
            # 스트리밍 커서 사용
            async with conn.transaction():
                async for row in conn.cursor(f"SELECT * FROM {table}"):
                    try:
                        doc = transformer(row)
                        doc_id = doc.get(id_field) or str(hash(str(doc)))

                        yield {
                            "_index": index,
                            "_id": doc_id,
                            "_source": doc,
                        }
                    except Exception as e:
                        logger.warning(f"Transform error for {table}: {e}")
                        continue

    async def migrate_table(
        self,
        table: str,
        index: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> MigrationStats:
        """
        단일 테이블 마이그레이션

        Args:
            table: PostgreSQL 테이블명
            index: ES 인덱스명 (기본값: TABLE_INDEX_MAP에서 조회)
            progress_callback: 진행률 콜백 (migrated, total)

        Returns:
            마이그레이션 통계
        """
        if index is None:
            index = self.TABLE_INDEX_MAP.get(table)
            if index is None:
                raise ValueError(f"Unknown table: {table}")

        start_time = datetime.now()
        total_rows = await self._get_table_count(table)

        logger.info(f"Starting migration: {table} → {index} ({total_rows:,} rows)")

        es = await self._get_es_client()
        transformer = self._get_transformer(table)
        id_field = self.ID_FIELD_MAP.get(table, "id")

        migrated = 0
        failed = 0

        pool = await self._get_pg_pool()

        async with pool.acquire() as conn:
            # 배치 단위로 처리
            offset = 0

            while offset < total_rows:
                rows = await conn.fetch(
                    f"SELECT * FROM {table} LIMIT {self.batch_size} OFFSET {offset}"
                )

                if not rows:
                    break

                actions = []
                for row in rows:
                    try:
                        doc = transformer(row)
                        doc_id = doc.get(id_field) or str(hash(str(doc)))

                        actions.append({
                            "_index": index,
                            "_id": doc_id,
                            "_source": doc,
                        })
                    except Exception as e:
                        logger.warning(f"Transform error: {e}")
                        failed += 1
                        continue

                # Bulk 인덱싱
                if actions:
                    try:
                        success, errors = await async_bulk(
                            es,
                            actions,
                            raise_on_error=False,
                            raise_on_exception=False,
                        )
                        migrated += success
                        failed += len(errors) if errors else 0

                        if errors:
                            for err in errors[:3]:  # 처음 3개만 로깅
                                logger.warning(f"Bulk error: {err}")

                    except Exception as e:
                        logger.error(f"Bulk indexing error: {e}")
                        failed += len(actions)

                offset += self.batch_size

                if progress_callback:
                    progress_callback(migrated, total_rows)

                # 진행률 로깅 (10% 단위)
                if offset % (self.batch_size * 10) == 0:
                    pct = (offset / total_rows) * 100 if total_rows > 0 else 0
                    logger.info(f"  Progress: {pct:.1f}% ({migrated:,} migrated)")

        elapsed = (datetime.now() - start_time).total_seconds()

        stats = MigrationStats(
            table=table,
            index=index,
            total_rows=total_rows,
            migrated=migrated,
            failed=failed,
            elapsed_seconds=elapsed,
        )

        logger.info(f"Completed: {stats}")
        return stats

    async def migrate_all(
        self,
        tables: Optional[List[str]] = None,
    ) -> List[MigrationStats]:
        """
        모든 테이블 마이그레이션

        Args:
            tables: 마이그레이션할 테이블 목록 (기본값: 전체)

        Returns:
            테이블별 마이그레이션 통계
        """
        if tables is None:
            tables = list(self.TABLE_INDEX_MAP.keys())

        stats_list = []

        for table in tables:
            try:
                stats = await self.migrate_table(table)
                stats_list.append(stats)
            except Exception as e:
                logger.error(f"Migration failed for {table}: {e}")
                stats_list.append(MigrationStats(
                    table=table,
                    index=self.TABLE_INDEX_MAP.get(table, "unknown"),
                    total_rows=0,
                    migrated=0,
                    failed=1,
                    elapsed_seconds=0,
                ))

        return stats_list

    async def incremental_sync(
        self,
        table: str,
        since: datetime,
        timestamp_field: str = "updated_at",
    ) -> MigrationStats:
        """
        증분 동기화

        특정 시점 이후 변경된 데이터만 동기화합니다.

        Args:
            table: 테이블명
            since: 기준 시점
            timestamp_field: 타임스탬프 필드명

        Returns:
            마이그레이션 통계
        """
        index = self.TABLE_INDEX_MAP.get(table)
        if index is None:
            raise ValueError(f"Unknown table: {table}")

        start_time = datetime.now()

        pool = await self._get_pg_pool()
        es = await self._get_es_client()
        transformer = self._get_transformer(table)
        id_field = self.ID_FIELD_MAP.get(table, "id")

        async with pool.acquire() as conn:
            # 변경된 행 조회
            query = f"""
                SELECT * FROM {table}
                WHERE {timestamp_field} >= $1
                ORDER BY {timestamp_field}
            """
            rows = await conn.fetch(query, since)

            total_rows = len(rows)
            logger.info(f"Incremental sync: {table} ({total_rows} rows since {since})")

            if not rows:
                return MigrationStats(
                    table=table,
                    index=index,
                    total_rows=0,
                    migrated=0,
                    failed=0,
                    elapsed_seconds=0,
                )

            actions = []
            for row in rows:
                try:
                    doc = transformer(row)
                    doc_id = doc.get(id_field)
                    actions.append({
                        "_index": index,
                        "_id": doc_id,
                        "_source": doc,
                    })
                except Exception as e:
                    logger.warning(f"Transform error: {e}")

            migrated = 0
            failed = 0

            if actions:
                success, errors = await async_bulk(
                    es,
                    actions,
                    raise_on_error=False,
                )
                migrated = success
                failed = len(errors) if errors else 0

        elapsed = (datetime.now() - start_time).total_seconds()

        return MigrationStats(
            table=table,
            index=index,
            total_rows=total_rows,
            migrated=migrated,
            failed=failed,
            elapsed_seconds=elapsed,
        )

    async def close(self):
        """연결 종료"""
        if self._es_client:
            await self._es_client.close()
            self._es_client = None

        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None


# CLI 인터페이스
async def main():
    """CLI 진입점"""
    import argparse

    parser = argparse.ArgumentParser(description="ES Data Migrator")
    parser.add_argument("action", choices=["migrate", "sync"])
    parser.add_argument("--table", "-t", help="Target table (default: all)")
    parser.add_argument("--batch-size", "-b", type=int, default=5000, help="Batch size")

    args = parser.parse_args()

    migrator = ESMigrator(batch_size=args.batch_size)

    try:
        if args.action == "migrate":
            if args.table:
                stats = await migrator.migrate_table(args.table)
                print(f"\n{stats}")
            else:
                stats_list = await migrator.migrate_all()
                print("\n=== Migration Summary ===")
                total_migrated = 0
                total_rows = 0
                for s in stats_list:
                    print(f"  {s}")
                    total_migrated += s.migrated
                    total_rows += s.total_rows
                print(f"\nTotal: {total_migrated:,}/{total_rows:,} documents migrated")

        elif args.action == "sync":
            # 증분 동기화 (24시간 이내 변경분)
            since = datetime.now() - timedelta(hours=24)
            if args.table:
                stats = await migrator.incremental_sync(args.table, since)
                print(f"\n{stats}")
            else:
                print("Incremental sync requires --table option")

    finally:
        await migrator.close()


if __name__ == "__main__":
    from datetime import timedelta
    asyncio.run(main())
