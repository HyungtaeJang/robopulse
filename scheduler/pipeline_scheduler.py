"""
scheduler/pipeline_scheduler.py
---------------------------------
APScheduler 기반 완전 자동화 파이프라인.
뉴스 수집(매 1시간), 영상 수집(매일 새벽 3시), LLM 분석(수집 직후)을
사람 개입 없이 자동으로 실행하고 결과를 DB에 기록합니다.
"""
import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()
logger = logging.getLogger(__name__)

NEWS_INTERVAL_HOURS = int(os.getenv("NEWS_FETCH_INTERVAL_HOURS", "1"))
VIDEO_CRON_HOUR = int(os.getenv("VIDEO_FETCH_CRON_HOUR", "3"))
ANALYSIS_CRON_HOUR = int(os.getenv("ANALYSIS_CRON_HOUR", "4"))


# ---- 파이프라인 작업 함수들 ---------------------------------

def job_fetch_news():
    """뉴스 RSS 전체 수집 후 DB 저장까지만 수행하는 가벼운 파이프라인"""
    from ingestion.news_scraper import run_all_sources
    
    logger.info("📰 [뉴스 파이프라인] 시작")
    start = datetime.now()

    try:
        # Step 1: 수집 (분석은 심야 배치로 이관)
        result = run_all_sources()
        logger.info(f"수집 완료: {result}")

        elapsed = (datetime.now() - start).total_seconds()
        _log_pipeline(source="news", status="success",
                      fetched=result["fetched"], skipped=result["skipped"], saved=result["saved"])
        logger.info(f"✅ [뉴스 파이프라인] 완료 ({elapsed:.1f}초)")

    except Exception as e:
        _log_pipeline(source="news", status="failure", error_msg=str(e))
        logger.error(f"❌ [뉴스 파이프라인] 오류: {e}")
        raise

def job_analyze_unprocessed(progress_callback=None, model_name=None):
    """뉴스 수집 없이 DB에 저장된 미처리 기사들만 골라 LLM 분석을 수행합니다."""
    from engine.gemma_worker import analyze_article
    from engine.graph_builder import add_analysis_to_graph
    from db.vector_store import (
        get_unprocessed_articles, save_analysis_result, 
        get_system_setting, get_available_lms_models
    )
    
    logger.info("🤖 [미처리 데이터 분석] 시작")
    start = datetime.now()
    
    try:
        # DB에서 설정된 배치 제한 읽기 (기본 100)
        limit_str = get_system_setting("analysis_batch_limit", "100")
        limit = int(limit_str) if limit_str and limit_str.isdigit() else 100
        
        # 모델 자동 감지 로직 (scheduler 호출 시 대비)
        if not model_name:
            # 1순위: DB에 저장된 활성 모델 (app.py에서 동기화됨)
            model_name = get_system_setting("active_lms_model")
            
            # 2순위: DB에 없으면 서버 로드 모델 중 첫 번째
            if not model_name:
                try:
                    models = get_available_lms_models()
                    if models:
                        model_name = models[0]
                        logger.info(f"자동 감지된 모델 사용: {model_name}")
                except:
                    pass

        unprocessed = get_unprocessed_articles(limit=limit)
        if not unprocessed:
            logger.info("분석할 미처리 기사가 없습니다.")
            if progress_callback:
                progress_callback(0, 0)
            return

        total = len(unprocessed)
        logger.info(f"LLM 분석 대상: {total}건 (모델: {model_name or 'Default'})")
        
        success_count = 0
        error_count = 0
        for i, article in enumerate(unprocessed, 1):
            try:
                analysis = analyze_article(
                    title=article["title"],
                    content=article["content"],
                    source=article["source"],
                    model_name=model_name,
                )
                if analysis:
                    save_analysis_result(article["id"], analysis)
                    add_analysis_to_graph(
                        article_id=article["id"],
                        entities=[e.model_dump() for e in analysis.entities],
                        relations=[r.model_dump() for r in analysis.relations],
                    )
                    success_count += 1
                else:
                    error_count += 1
            except RuntimeError as re:
                if "FATAL_LLM_ERROR" in str(re):
                    logger.error(f"🛑 [치명적 오류] 분석을 중단합니다: {re}")
                    _log_pipeline(source="analysis", status="failure", error_msg=f"치명적 오류로 중단: {re}")
                    if progress_callback: progress_callback(-1, 0)
                    return # 즉시 종료

            # 콜백을 통해 실시간 진행률 보고 (현재 수, 전체 수)
            if progress_callback:
                progress_callback(i, total)
        
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"✅ [분석 완료] {success_count}/{total}건 처리됨 ({elapsed:.1f}초)")
        
        # 파이프라인 로그 기록
        _log_pipeline(
            source="analysis", 
            status="success", 
            fetched=total, 
            saved=success_count,
            skipped=total - success_count
        )
        
    except Exception as e:
        logger.error(f"❌ [분석 오류] {e}")
        _log_pipeline(source="analysis", status="failure", error_msg=str(e))
        if progress_callback:
            progress_callback(-1, 0) # 오류 발생 신호


def job_fetch_videos():
    """유튜브 채널 자막 수집 후 DB 저장까지만 수행하는 파이프라인"""
    from ingestion.video_processor import run_all_channels

    logger.info("🎬 [영상 파이프라인] 시작")
    start = datetime.now()

    try:
        result = run_all_channels()
        logger.info(f"수집 완료: {result}")

        elapsed = (datetime.now() - start).total_seconds()
        _log_pipeline(source="youtube", status="success",
                      fetched=result["fetched"], skipped=result["skipped"], saved=result["saved"])
        logger.info(f"✅ [영상 파이프라인] 완료 ({elapsed:.1f}초)")

    except Exception as e:
        _log_pipeline(source="youtube", status="failure", error_msg=str(e))
        logger.error(f"❌ [영상 파이프라인] 오류: {e}")
        raise


def _log_pipeline(source: str, status: str,
                  fetched: int = 0, skipped: int = 0, saved: int = 0,
                  error_msg: str = None):
    """파이프라인 실행 결과를 pipeline_logs 테이블에 기록합니다."""
    try:
        from db.vector_store import _get_session
        import uuid
        session = _get_session()
        session.execute(text("""
            INSERT INTO pipeline_logs (id, source, status, fetched, skipped, saved, error_msg)
            VALUES (:id, :source, :status, :fetched, :skipped, :saved, :error_msg)
        """), {
            "id": str(uuid.uuid4()),
            "source": source, "status": status,
            "fetched": fetched, "skipped": skipped, "saved": saved,
            "error_msg": error_msg,
        })
        session.commit()
        session.close()
    except Exception as e:
        logger.warning(f"로그 저장 실패: {e}")


# ---- 스케줄러 인스턴스 ------------------------------------
_scheduler: BackgroundScheduler | None = None


def _on_job_event(event):
    if event.exception:
        logger.error(f"[스케줄러] 작업 실패: {event.job_id} - {event.exception}")
    else:
        logger.info(f"[스케줄러] 작업 완료: {event.job_id}")


def start_scheduler() -> BackgroundScheduler:
    """스케줄러를 시작하고 인스턴스를 반환합니다."""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.info("스케줄러가 이미 실행 중입니다.")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    _scheduler.add_listener(_on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # 뉴스 RSS: 매 N시간마다
    _scheduler.add_job(
        job_fetch_news,
        trigger="interval",
        hours=NEWS_INTERVAL_HOURS,
        id="news_pipeline",
        name="뉴스 RSS 수집 파이프라인",
        max_instances=1,
        misfire_grace_time=600,  # 10분 내에 시작 못하면 스킵
    )

    # 유튜브 자막: 매일 새벽 VIDEO_CRON_HOUR시
    _scheduler.add_job(
        job_fetch_videos,
        trigger="cron",
        hour=VIDEO_CRON_HOUR,
        minute=0,
        id="video_pipeline",
        name="유튜브 자막 수집 파이프라인",
        max_instances=1,
        misfire_grace_time=1800,  # 30분 내에 시작 못하면 스킵
    )

    # 심야 AI 심층 분석: 매일 새벽 ANALYSIS_CRON_HOUR시 30분
    _scheduler.add_job(
        job_analyze_unprocessed,
        trigger="cron",
        hour=ANALYSIS_CRON_HOUR,
        minute=30,
        id="analysis_pipeline",
        name="야간 AI 심층 분석",
        max_instances=1,
        misfire_grace_time=1800,  # 30분 내에 시작 못하면 스킵
    )

    _scheduler.start()
    logger.info(f"✅ 스케줄러 시작 | 뉴스: 매 {NEWS_INTERVAL_HOURS}시간 | "
                f"영상: 매일 {VIDEO_CRON_HOUR:02d}:00 | 분석: 매일 {ANALYSIS_CRON_HOUR:02d}:30")
    return _scheduler


def stop_scheduler():
    """스케줄러를 안전하게 중지합니다."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("스케줄러 중지 완료")


def get_scheduler_status() -> list[dict]:
    """현재 스케줄된 작업 목록과 다음 실행 시각을 반환합니다."""
    if not _scheduler:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        # 다음 실행 시각을 HH:mm 형식으로 포맷팅
        next_run_str = job.next_run_time.strftime("%H:%M") if job.next_run_time else "대기 중"
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run_str,
        })
    return jobs


def update_analysis_schedule(hour: int) -> bool:
    """야간 AI 심층 분석의 실행 시간을 동적으로 변경합니다."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.reschedule_job("analysis_pipeline", trigger="cron", hour=hour, minute=30)
        logger.info(f"✅ AI 분석 스케줄 변경 완료: 매일 {hour:02d}:30")
        return True
    return False
