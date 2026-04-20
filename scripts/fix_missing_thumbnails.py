import os
import sys
import logging

# 프로젝트 루트를 경로에 추가 (ingestion 및 db 모듈을 불러오기 위함)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from ingestion.news_scraper import _extract_full_text_and_image
from db.vector_store import _get_session
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def fix_thumbnails(limit=50):
    """이미지가 누락된 기사들의 썸네일을 재수집하여 업데이트합니다."""
    session = _get_session()
    try:
        # 이미지가 없는 최근 기사 조회 (뉴스 타입만)
        query = text("""
            SELECT id, url, title 
            FROM articles 
            WHERE (thumbnail_url IS NULL OR thumbnail_url = '') 
            AND source_type = 'news'
            ORDER BY collected_at DESC 
            LIMIT :limit
        """)
        articles = session.execute(query, {"limit": limit}).fetchall()
        
        if not articles:
            logger.info("✅ 보정할 대상 기사가 없습니다.")
            return

        logger.info(f"🔎 보정 대상 기사 발견: {len(articles)}건 (최근 수집순)")
        
        fixed_count = 0
        for art in articles:
            # SQLAlchemy Row 객체 대응 (index or mapping)
            art_id = art[0]
            url = art[1]
            title = art[2]
            
            logger.info(f"  → 처리 중: {title[:40]}...")
            
            try:
                # 고도화된 추출 로직 재사용
                _, thumbnail_url = _extract_full_text_and_image(url)
                
                if thumbnail_url:
                    update_query = text("UPDATE articles SET thumbnail_url = :thumb WHERE id = :id")
                    session.execute(update_query, {"thumb": thumbnail_url, "id": art_id})
                    session.commit()
                    fixed_count += 1
                    logger.info(f"    ✅ 이미지 복구 성공! ({thumbnail_url[:60]}...)")
                else:
                    logger.info("    [-] 원본 페이지에서 유효한 이미지를 찾지 못했습니다.")
            except Exception as e:
                logger.error(f"    ⚠️ 개별 기사 처리 중 오류: {e}")
                session.rollback()
                
        logger.info(f"✨ 보정 작업 완료! 총 {fixed_count}건의 이미지를 복구했습니다.")
        
    except Exception as e:
        logger.error(f"🚨 보정 작업 중 심각한 오류 발생: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    # 사용법: python3 fix_missing_thumbnails.py [제한개수]
    # 예: python3 fix_missing_thumbnails.py 100
    target_limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    fix_thumbnails(limit=target_limit)
