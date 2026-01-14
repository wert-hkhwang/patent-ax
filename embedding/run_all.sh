#!/bin/bash
# EP-Agent: 전체 임베딩 실행 스크립트
# 순차적으로 실행 (안정성 우선)

LOG_DIR="/root/AX/clean/logs"
EMBED_DIR="/root/AX/clean/embedding"

echo "=========================================="
echo "EP-Agent 임베딩 파이프라인 시작"
echo "시작 시간: $(date)"
echo "=========================================="

# 1. 제안서
echo ""
echo "[1/5] 제안서 임베딩..."
python3 $EMBED_DIR/embed_proposal.py 2>&1 | tee $LOG_DIR/embed_proposal.log
echo "제안서 완료: $(date)"

# 2. 특허
echo ""
echo "[2/5] 특허 임베딩..."
python3 $EMBED_DIR/embed_patent.py 2>&1 | tee $LOG_DIR/embed_patent.log
echo "특허 완료: $(date)"

# 3. 과제
echo ""
echo "[3/5] 과제 임베딩..."
python3 $EMBED_DIR/embed_project.py 2>&1 | tee $LOG_DIR/embed_project.log
echo "과제 완료: $(date)"

# 4. 장비
echo ""
echo "[4/5] 장비 임베딩..."
python3 $EMBED_DIR/embed_equipment.py 2>&1 | tee $LOG_DIR/embed_equipment.log
echo "장비 완료: $(date)"

# 5. 공고/KPI
echo ""
echo "[5/5] 공고/KPI 임베딩..."
python3 $EMBED_DIR/embed_announcement.py 2>&1 | tee $LOG_DIR/embed_announcement.log
echo "공고/KPI 완료: $(date)"

echo ""
echo "=========================================="
echo "전체 임베딩 완료"
echo "종료 시간: $(date)"
echo "=========================================="
