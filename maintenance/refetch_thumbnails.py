import os
import sys
import logging
from sqlalchemy import text

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from db.vector_store import _get_session
from ingestion.news_scraper import is_valid_image, _extract_full_text_and_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("thumbnail_fixer")

def fix_existing_thumbnails():
    session = _get_session()
    try:
        # 1. 모든 기사 조회 (또는 조건부 조회)
        logger.info("🛠️ 수리가 필요한 기존 기사 목록을 조회 중...")
        result = session.execute(text("SELECT id, url, thumbnail_url, title FROM articles"))
        articles = result.fetchall()
        
        targets = []
        for row in articles:
            aid, url, thumb, title = row
            # 유효하지 않은 이미지(구글 로고 등)인 경우 수리 대상으로 등록
            if not thumb or not is_valid_image(thumb):
                targets.append((aid, url, title))

        logger.info(f"📋 총 {len(targets)}개의 기사가 수리 대상으로 선정되었습니다.")

        if not targets:
            logger.info("이미 모든 썸네일이 깨끗합니다! 작업할 내용이 없습니다.")
            return

        # 2. 수리 시작
        fixed_count = 0
        for i, (aid, url, title) in enumerate(targets):
            try:
                # 너무 잦은 요청 방지 (약간의 지연)
                import time
                time.sleep(0.5)

                logger.info(f"[{i+1}/{len(targets)}] 수리 중: {title[:40]}...")
                
                # 원본 URL에서 다시 이미지 추출
                _, new_thumb = _extract_full_text_and_image(url)
                
                if new_thumb and is_valid_image(new_thumb):
                    logger.info(f"   ㄴ 📸 이미지 발견! -> {new_thumb[:80]}...")
                    session.execute(
                        text("UPDATE articles SET thumbnail_url = :t WHERE id = :id"),
                        {"t": new_thumb, "id": aid}
                    )
                    fixed_count += 1
                    if fixed_count % 5 == 0: # 5개마다 실시간 반영
                        session.commit()
                        logger.info(f"✨ 현재 {fixed_count}개 수리 완료...")
                else:
                    logger.info("   ㄴ ⏭️ 유효한 이미지를 찾지 못했습니다.")
                
            except Exception as e:
                logger.warning(f"❌ {title[:20]} 수리 실패: {e}")
                continue

        session.commit()
        logger.info(f"🎉 모든 작업 완료! 총 {fixed_count}개의 썸네일이 새 이미지로 교체되었습니다.")

    except Exception as e:
        logger.error(f"치명적 오류 발생: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    fix_existing_thumbnails()
