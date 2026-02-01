#!/usr/bin/env python3
"""
데이터베이스 연결 및 존재 여부 확인 스크립트
"""

import sys
import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from core.config import settings

async def check_database():
    """데이터베이스 연결 및 존재 여부 확인"""
    
    print("=" * 60)
    print("데이터베이스 연결 확인")
    print("=" * 60)
    
    # DATABASE_URL 파싱
    db_url = settings.database_url
    print(f"\n📋 DATABASE_URL: {db_url}")
    
    # 데이터베이스 이름 추출
    db_name = db_url.split("/")[-1].split("?")[0]
    print(f"📋 데이터베이스 이름: {db_name}")
    
    # PostgreSQL 서버에 연결 (postgres 데이터베이스 사용)
    server_url = db_url.rsplit("/", 1)[0] + "/postgres"
    print(f"\n🔌 서버 연결 시도: {server_url}")
    
    try:
        engine = create_engine(server_url, echo=False)
        
        with engine.connect() as conn:
            # 데이터베이스 목록 확인
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname = :db_name"), {"db_name": db_name})
            db_exists = result.fetchone()
            
            if db_exists:
                print(f"✅ 데이터베이스 '{db_name}' 존재함")
                
                # 실제 데이터베이스에 연결 시도
                print(f"\n🔌 데이터베이스 '{db_name}' 연결 시도...")
                try:
                    target_engine = create_engine(db_url, echo=False)
                    with target_engine.connect() as target_conn:
                        # 테이블 목록 확인
                        result = target_conn.execute(text("""
                            SELECT table_name 
                            FROM information_schema.tables 
                            WHERE table_schema = 'public'
                            ORDER BY table_name
                        """))
                        tables = result.fetchall()
                        
                        if tables:
                            print(f"\n📊 테이블 목록 ({len(tables)}개):")
                            for table in tables:
                                print(f"  - {table[0]}")
                        else:
                            print(f"\n⚠️  데이터베이스 '{db_name}'에 테이블이 없습니다.")
                            print("   (Aura-Platform은 현재 데이터베이스 테이블을 사용하지 않습니다)")
                        
                        print(f"\n✅ 데이터베이스 '{db_name}' 연결 성공")
                except OperationalError as e:
                    print(f"\n❌ 데이터베이스 '{db_name}' 연결 실패: {e}")
                    return False
            else:
                print(f"\n⚠️  데이터베이스 '{db_name}'가 존재하지 않습니다.")
                print(f"\n💡 데이터베이스 생성 방법:")
                print(f"   docker exec -it dwp-postgres psql -U <사용자명> -d postgres -c \"CREATE DATABASE {db_name};\"")
                return False
        
        return True
        
    except OperationalError as e:
        print(f"\n❌ PostgreSQL 서버 연결 실패: {e}")
        print("\n💡 확인 사항:")
        print("   1. PostgreSQL 컨테이너가 실행 중인지 확인: docker ps | grep postgres")
        print("   2. DATABASE_URL의 호스트, 포트, 사용자명, 비밀번호가 올바른지 확인")
        print("   3. .env 파일의 DATABASE_URL 설정 확인")
        return False
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(check_database())
    sys.exit(0 if success else 1)
