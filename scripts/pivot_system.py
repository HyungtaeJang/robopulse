"""
RoboPulse 홈로봇 피벗 지원 스크립트
---------------------------------
사용법: python3 scratch/pivot_system.py --init
(주의: --init 옵션 사용 시 기존 데이터가 모두 초기화됩니다.)
"""
import sys
import os
import argparse
from sqlalchemy import text

# 현재 경로를 PYTHONPATH에 추가하여 모듈 임포트 가능하게 함
sys.path.insert(0, os.getcwd())

from db.vector_store import _get_session, clear_all_data

def seed_recommendations(session):
    print("🎬 휴머노이드 및 홈로봇 전문 소스 추천함(AI 추천함) 적재 중...")
    sources = [
        ("https://www.youtube.com/@1X-tech", "video", "1X Technologies", "최첨단 이족보행 및 가사용 휴머노이드 개발 기업"),
        ("https://www.youtube.com/@FigureAI", "video", "Figure AI", "상용 휴머노이드 Figure 01/02 개발 선두주자"),
        ("https://www.youtube.com/@Tesla", "video", "Tesla Optimus", "테슬라의 범용 인간형 로봇 Optimus 공식 채널"),
        ("https://www.youtube.com/@UnitreeRobotics", "video", "Unitree Robotics", "H1, G1 휴머노이드로 시장을 주도하는 기업"),
        ("https://www.youtube.com/@Apptronik", "video", "Apptronik", "범용 휴머노이드 Apollo 개발 기업"),
        ("https://www.youtube.com/@AgilityRobotics", "video", "Agility Robotics", "물류 및 가사 보조 가능성 높은 Digit 개발사"),
        ("https://www.youtube.com/@SanctuaryAI", "video", "Sanctuary AI", "지능형 제어 시스템 기반 Phoenix 개발사"),
        ("https://spectrum.ieee.org/feeds/topic/humanoid-robots.rss", "news", "IEEE Spectrum - Humanoids", "전 세계 휴머노이드 기술 심층 리포트"),
        ("https://www.therobotreport.com/category/robotics-topics/mobile-robots/feed/", "news", "The Robot Report - Mobile", "이동형 서비스 로봇 전문 섹션"),
        ("https://www.youtube.com/@Dyson", "video", "Dyson (Robotics)", "차세대 가사 자동화 로봇 연구 및 개발 채널")
    ]
    
    for url, s_type, label, reason in sources:
        session.execute(text("""
            INSERT INTO recommended_sources (url, source_type, label, reason, status)
            VALUES (:u, :t, :l, :r, 'pending')
            ON CONFLICT(url) DO UPDATE SET status='pending'
        """), {"u": url, "t": s_type, "l": label, "r": reason})
    session.commit()
    print("✅ 추천 소스 적재 완료.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="기존 데이터를 초기화합니다.")
    args = parser.parse_args()

    session = _get_session()
    try:
        if args.init:
            print("🚨 기존 데이터 초기화 중...")
            clear_all_data(reset_sources=True)
            print("✅ 초기화 완료.")
        
        seed_recommendations(session)
        print("\n✨ 모든 작업이 완료되었습니다. 이제 Streamlit 앱을 재시작하고 [AI 기반 소스 추천] 탭을 확인하세요.")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    main()
