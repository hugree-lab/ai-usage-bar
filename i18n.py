"""Lightweight Korean/English i18n module with OS locale auto-detection for AI Usage Bar."""

from __future__ import annotations

import ctypes
import locale
import os
import subprocess
import sys
from typing import Dict

LANG_CHOICES = ("auto", "ko", "en")


def detect_os_language() -> str:
    """Return 'ko' if the OS UI language is Korean, otherwise 'en'."""
    try:
        if sys.platform == "win32":
            # Win32 GetUserDefaultUILanguage primary lang ID: Korean == 0x12
            lang_id = int(ctypes.WinDLL("kernel32").GetUserDefaultUILanguage())
            return "ko" if (lang_id & 0x3FF) == 0x12 else "en"
        if sys.platform == "darwin":
            proc = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True, text=True, timeout=1.5,
            )
            if proc.returncode == 0:
                first_lines = " ".join(proc.stdout.splitlines()[:3]).lower()
                if "ko" in first_lines:
                    return "ko"
                return "en"
    except Exception:
        pass

    env_lang = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    if env_lang.startswith("ko"):
        return "ko"
    try:
        loc = (locale.getdefaultlocale()[0] or "").lower()
        if loc.startswith("ko"):
            return "ko"
    except Exception:
        pass
    return "en"


def resolve_lang(pref: str = "auto") -> str:
    p = (pref or "auto").lower()
    if p in ("ko", "en"):
        return p
    return detect_os_language()


STRINGS: Dict[str, Dict[str, str]] = {
    "ko": {
        # HUD header & titles
        "hud_title_used": "AI 주간 사용량",
        "hud_title_rem": "AI 주간 잔여량",
        "tip_title": "드래그: 이동 · 더블클릭: 작업표시줄 위로 정렬",
        "tip_refresh_busy": "새로고침 진행 중...",
        "tip_refresh": "지금 새로고침 (사용량 차감 없음)",
        "tip_collapse": "최소창으로 접기",
        "tip_expand": "상세 보기 펼치기",
        "tip_settings": "설정 · 추이 · 사용 안내",
        "tip_pin_on": "항상 최상위 고정 (켜짐)",
        "tip_pin_off": "항상 최상위 고정 (꺼짐)",
        "tip_hide": "시스템 트레이로 숨기기",
        "tip_hide_macos": "숨기기 (Dock 아이콘 클릭으로 다시 보이기)",
        "tip_move_up": "표시 순서 위로 이동",
        "tip_move_dn": "표시 순서 아래로 이동",

        # Compact / detail labels
        "waiting": "대기중",
        "waiting_conn": "연동 대기",
        "waiting_resp": "응답대기",
        "waiting_resp_sp": "응답 대기",
        "reset_short": "리셋",
        "reset_done": "초기화됨",
        "reset_done_short": "초기화",
        "reset_tooltip": "리셋됨 (초기화 완료)",
        "none_avail": "없음",
        "cli_unavailable": "CLI 미제공",
        "after_first_chat": "1회 대화 후 표시",
        "days_7": "7일",
        "weekly_gen": "일반 주간",
        "weekly_argon": "Argon 주간",
        "weekly_fable": "Fable 주간",
        "weekly_7d": "주간 (7일)",
        "session_5h": "5시간 단기",
        "third_party_wk": "3P 주간",
        "src_agy": "agy 자동",
        "src_cld_auto": "자동 갱신",
        "src_cld_hook": "Claude 자동",
        "src_cdx_log": "세션 로그",
        "src_cdx_auto": "Codex 자동",
        "hint_agy": "agy 터미널 실행 시 자동 수신",
        "hint_cld": "claude 로그인(구독) 후 자동 수신",
        "hint_cld_sync": "Claude Pro/Max 자동 동기화",
        "hint_cdx": "codex CLI / 세션 기록 자동 연동",

        # Detail bottom bar
        "lbl_providers": "표시 AI",
        "lbl_compact": "최소창",
        "style_dual": "2줄",
        "style_slim": "슬림",
        "style_ring": "원형",
        "style_dual_title": "2줄 (주간+5h)",
        "style_dual_sub": "주간 + 5시간 동시 표시",
        "style_dual_desc": "주간 바와 5시간 단기 바·남은 시간을\n2줄 수직 정렬 카드로 한눈에 표시합니다.",
        "style_slim_title": "1줄 슬림",
        "style_slim_sub": "초슬림 높이 · 2단 바",
        "style_slim_desc": "가장 작은 높이(99px)에 위(주간)/아래(5h) 2단 바 표시.\n우측 숫자를 클릭하면 5h ↔ 모델별(Ar·Fb)로 전환됩니다.",
        "style_ring_title": "원형 2중 링",
        "style_ring_sub": "바깥=주간 · 안쪽=5h",
        "style_ring_desc": "안티앨리어싱 2중 원형 게이지로 바깥 링은 주간,\n안쪽 링은 5시간 단기 사용량을 감각적으로 표시합니다.",
        "btn_mode_used": "표시: 사용%",
        "btn_mode_rem": "표시: 남음%",
        "btn_snap": "정렬",
        "btn_settings_all": "⚙ 설정 · 추이 · 안내",

        # Context menu
        "menu_refresh": "지금 새로고침",
        "menu_details": "상세 보기",
        "menu_topmost": "항상 최상위 고정",
        "menu_snap": "작업표시줄 위로 이동",
        "menu_hide": "위젯 숨기기",
        "menu_show": "위젯 보이기",
        "menu_trends": "사용 추이 / 페이스",
        "menu_settings": "설정 · 단축키 · 안내...",
        "menu_quit": "종료",

        # Tooltips & tray
        "mode_used_word": "사용량",
        "mode_rem_word": "남은량",
        "mode_basis": "{mode} 기준",
        "tip_pace": "페이스: {label}",
        "tip_note": "안내: {msg}",
        "tip_updated_slim": "갱신: {age} · 우측 클릭: 5h↔모델별",
        "tip_updated_dbl": "갱신: {age} · 더블클릭: 상세 보기",
        "tip_click_refresh": "↻ 클릭으로 즉시 갱신 · 더블클릭: 상세 보기",
        "tray_wk_prefix": "주간",

        # Notifications
        "noti_test_title": "AI Usage Bar 알림 테스트",
        "noti_test_body": "데스크톱 알림이 정상적으로 동작하고 있습니다.",
        "noti_reset_title": "{label} 한도 초기화",
        "noti_reset_body": "할당량이 리셋되어 다시 사용할 수 있습니다.",
        "noti_reset_new_body": "새 주기 할당량이 초기화되었습니다.",
        "noti_crit_title": "{label} 한도 임박 ({pct:.0f}%)",
        "noti_crit_body": "설정 임박 기준({th}%) 도달",
        "noti_warn_title": "{label} 사용량 {pct:.0f}% 도달",
        "noti_warn_body": "설정 주의 기준({th}%) · 남은량 {rem:.0f}%",
        "noti_until_reset": "리셋까지 {cd}",

        # Settings dialog
        "set_win_title": "AI Usage Bar 설정  v{ver}",
        "tab_display": "화면 · 순서",
        "tab_alerts": "알림 · 단축키",
        "tab_trends": "사용 추이",
        "tab_help": "사용 안내",
        "btn_open_data": "데이터 폴더 열기",
        "btn_close": "닫기",
        "sec_style_title": "최소창 스타일 미리보기",
        "sec_style_hint": "클릭 시 위젯에 바로 적용",
        "lbl_slim_sub": "슬림 우측 보조 표시:",
        "opt_slim_model": "모델별 (Ar·Fb)",
        "opt_slim_5h": "5시간 (5h)",
        "sec_order_title": "표시할 AI 및 순서",
        "sec_order_hint": "⠿ 잡고 위아래 드래그 또는 ▲/▼",
        "chip_shown": "표시",
        "chip_hidden": "숨김",
        "lbl_mode": "표시 기준",
        "lbl_pace_row": "페이스 눈금 (|) — 바 위 경과 시점",
        "lbl_mode_and_pace": "표시 기준 · 페이스 눈금",
        "chip_pace_marker": "페이스 눈금 |",
        "chip_used_pct": "사용량 %",
        "chip_rem_pct": "남은량 %",
        "lbl_theme": "테마",
        "lbl_lang": "언어",
        "lbl_theme_lang": "테마 · 언어",
        "theme_auto": "자동",
        "theme_dark": "다크",
        "theme_light": "라이트",
        "lang_auto": "OS 자동",
        "lbl_opacity": "위젯 투명도",

        # Hotkey manager & refresher diagnostics
        "hk_macos_note": "macOS: ⌘R(새로고침) · ⌘,(설정) · ⌘H(숨기기) · ⌘Q(종료) · Dock 클릭(복원)",
        "hk_init_err": "단축키 스레드 초기화 실패",
        "hk_disabled": "단축키 꺼짐",
        "hk_invalid": "지원하지 않는 단축키 형식 (예: Ctrl+Alt+Q)",
        "hk_in_use": "'{norm}'은(는) 다른 앱에서 사용 중입니다.",
        "hk_registered": "'{norm}' 등록 완료",
        "ref_agy_missing": "agy CLI 미설치",
        "ref_agy_err": "agy 실행 오류: {exc}",
        "ref_agy_ok": "Antigravity 갱신 완료",
        "ref_agy_login": "agy 로그인 필요 (터미널에서 agy 실행)",
        "ref_agy_timeout": "Antigravity 갱신 시간 초과",
        "ref_cld_missing": "Claude Code 미설치",
        "ref_cld_trust": "신뢰된 Claude 폴더 없음 (최초 1회 claude 실행 필요)",
        "ref_cld_err": "Claude 실행 오류: {exc}",
        "ref_cld_trust_once": "Claude 폴더 1회 신뢰 필요",
        "ref_cld_login": "Claude Pro/Max 로그인 필요 (/login)",
        "ref_cld_timeout": "Claude /usage 응답 없음 (로그인 확인)",
        "ref_cld_ok": "Claude 갱신 완료",
        "ref_cdx_ok": "Codex 갱신 완료",
        "ref_cdx_log_ok": "Codex 세션 로그 반영 완료",
        "ref_cdx_missing": "Codex 미설치 또는 사용 기록 없음",

        "sec_alert_title": "사용량 알림 수동 설정",
        "btn_alert_test": "🔔 알림 테스트",
        "chip_alert_on": "알림 켜짐",
        "chip_alert_off": "알림 꺼짐",
        "lbl_warn_th": "주의 알림 (사용량)",
        "lbl_crit_th": "임박 알림 (사용량)",
        "opt_off": "끄기",
        "lbl_alert_scope": "알림 범위 · 리셋",
        "chip_on_reset": "리셋 완료 알림",
        "chip_scope_all": "주간 + 5시간",
        "chip_scope_wk": "주간만",
        "sec_hotkey_title": "글로벌 단축키 (위젯 숨기기 / 보이기)",
        "chip_on": "사용 중",
        "chip_off": "꺼짐",
        "hk_recording": "조합키를 누르세요... (Esc 취소)",
        "hk_cancelled": "단축키 녹화를 취소했습니다.",
        "hk_hint": "예: Ctrl+Alt+Q, Ctrl+Shift+A, Alt+F9",
        "btn_hk_default": "기본값",
        "btn_hk_cancel": "녹화 취소",
        "btn_hk_change": "단축키 변경",
        "lbl_refresh_iv": "자동 새로고침 주기 (자리비움 시 일시정지)",
        "min_fmt": "{m}분",
        "chip_auto_refresh": "자동 새로고침",
        "chip_startup": "시작 시 자동 실행",
        "btn_reconnect": "⚡ 훅 재연결",
        "btn_reconnected": "재연결 완료 ✓",

        "trends_legend": "실선: 주간  ·  가는 선: 5시간  ·  점선: 주의 기준",
        "period_24h": "24시간",
        "period_7d": "7일",
        "pace_waiting": "페이스 계산 대기",
        "trends_points": "기록 {n}개 · 최근 갱신 {age}",
        "trends_collecting": "데이터 수집 중 · 자동 갱신 시 추이 곡선이 자동으로 그려집니다",

        "help_c1_title": "1. 화면 표시 · 페이스 눈금(|) · 색상 범례",
        "help_l1_k": "• 주간 (위 바 / 바깥 링)",
        "help_l1_v": "7일 전체 사용량(또는 남은량)입니다.",
        "help_l2_k": "• 5h (아래 바 / 안쪽 링)",
        "help_l2_v": "5시간 단기 한도와 남은 리셋 시간입니다.",
        "help_l3_k": "• Ar / Fb",
        "help_l3_v": "Antigravity Argon 주간 · Claude Fable 주간 한도입니다.",
        "help_l4_k": "• 바 위 세로 눈금 (|)",
        "help_l4_v": "전체 기간 중 현재 경과 시점입니다. 막대가 짧으면 여유, 길면 빠름!",
        "legend_ok": "여유 (시그니처)",
        "legend_warn": "주의 (75%+)",
        "legend_crit": "경고 ⚠ (90%+)",
        "legend_reset": "리셋 완료",
        "help_c2_title": "2. 편리한 단축 조작법",
        "help_s1_k": "• 최소창 행/원형 호버",
        "help_s1_v": "남은 일자·시간, 정확한 리셋 시각, 소진 페이스 예측이 뜹니다.",
        "help_s2_k": "• AI 행/원형 더블클릭",
        "help_s2_v": "상세 보기 펼치기 / 최소창 접기를 빠르게 전환합니다.",
        "help_s3_k": "• 제목 드래그 / 더블클릭",
        "help_s3_v": "드래그로 자유 이동, 더블클릭으로 현재 모니터 작업표시줄 위로 정렬.",
        "help_s4_k": "• 슬림 모드 우측 클릭",
        "help_s4_v": "1줄 슬림 모드에서 우측 숫자 클릭 시 5h ↔ 모델별(Ar·Fb) 전환.",
        "help_s5_k": "• 전역 단축키 ({hk})",
        "help_s5_v": "작업 중 어느 창에서든 위젯을 즉시 숨기거나 다시 띄웁니다.",
        "help_c3_title": "3. 사용량 차감 없는 자동 갱신 & 최초 로그인 안내",
        "help_c3_body": (
            "• 데스크톱 앱·웹만 사용해도 공식 CLI(agy / claude)를 숨김 조회해 사용량 차감 없이 자동 갱신합니다.\n"
            "• 5분 이상 입력이 없으면 백그라운드 조회를 쉬고, 복귀 시 자동으로 최신 값을 불러옵니다.\n"
            "• Antigravity: 터미널에서 `agy` 1회 실행 후 Google 계정 로그인\n"
            "• Claude: 터미널에서 `claude` → `/login` 시 반드시 구독 계정(Claude account with subscription) 선택\n"
            "• Codex (선택): `codex` CLI 설치/로그인 또는 세션 기록 자동 감지"
        ),

        # Uninstall dialog
        "uninst_title": "AI Usage Bar 제거",
        "uninst_confirm": (
            "AI Usage Bar를 제거하시겠습니까?\n\n"
            "- 실행 중인 위젯 종료\n"
            "- Claude Code / agy CLI statusLine 연결 해제\n"
            "- 시작 프로그램 및 바로가기 제거"
        ),
        "uninst_done": "제거가 완료되었습니다.",

        # Installer Wizard
        "wiz_title": "AI Usage Bar 설치 마법사 v{ver}",
        "wiz_header_sub": "  설치 마법사  v{ver}",
        "wiz_step1": "1. 시작",
        "wiz_step2": "2. 연동 및 옵션",
        "wiz_step3": "3. 설치 진행",
        "wiz_step4": "4. 완료",
        "wiz_cancel": "취소",
        "wiz_back": "< 이전",
        "wiz_next": "다음 >",
        "wiz_start": "설치 시작",
        "wiz_installing": "설치 중...",
        "wiz_retry": "다시 시도",
        "wiz_done": "완료",
        "wiz_welcome_h1": "Antigravity · Claude · Codex 사용량 위젯을 설치합니다",
        "wiz_welcome_sub": (
            "작업표시줄 위 항상 최상위 미니 바 + 시스템 트레이 아이콘으로\n"
            "주간(7일) / 단기(5시간) 사용량과 리셋 카운트다운·소진 페이스를 한눈에 확인하세요."
        ),
        "wiz_f1_t": "• Python 설치 불필요",
        "wiz_f1_d": "독립 실행형 앱과 17KB 초경량 네이티브 훅이 함께 설치됩니다.",
        "wiz_f2_t": "• 데스크톱 앱·웹만 써도 사용량 차감 없이 자동 갱신",
        "wiz_f2_d": "공식 CLI를 백그라운드 조회해 사용량 차감 없이 자동 갱신하며, 자리비움 시 일시정지합니다.",
        "wiz_f3_t": "• 3가지 최소창 스타일 미리보기 & 드래그 AI 순서 변경",
        "wiz_f3_d": "설정 창(⚙)에서 2줄 · 슬림 · 원형 링 스타일을 미리보기로 고르고, AI 순서를 드래그로 변경합니다.",
        "wiz_f4_t": "• 소진 페이스 · 추이 그래프 · 커스텀 알림 & 단축키 · 한/영 지원",
        "wiz_f4_d": "바 위 페이스 눈금(|), 24h/7d 사용 추이, 알림 기준/단축키 커스텀, 한국어/영어 전환을 지원합니다.",
        "wiz_welcome_foot": "계속하려면 [다음 >]을 눌러 환경 감지 및 연동 옵션을 확인하세요.",
        "wiz_env_title": "현재 PC 환경 감지 결과",
        "wiz_detected": "감지됨 ✓",
        "wiz_not_found_claude": "미설치 (추후 설치해도 설정 자동 적용)",
        "wiz_not_found_agy": "미설치 (아래 체크 시 자동 설치 가능)",
        "wiz_not_found_codex": "미설치 (필요 시 아래에서 표시 가능)",
        "wiz_show_ai": "위젯에 표시할 AI:",
        "wiz_opt_title": "자동 연동 및 설치 옵션",
        "wiz_opt_claude": "Claude Code 공식 statusLine 자동 연결 (~/.claude/settings.json 백업 후 설정)",
        "wiz_opt_agy": "Antigravity CLI (agy) 공식 statusLine 자동 연결",
        "wiz_opt_agy_inst_done": "Antigravity CLI (agy) 공식 설치 스크립트 자동 실행 (이미 설치됨)",
        "wiz_opt_agy_inst_rec": "Antigravity CLI (agy) 공식 설치 스크립트 자동 실행 (권장)",
        "wiz_opt_startup": "Windows 시작 시 AI Usage Bar 자동 실행 등록",
        "wiz_opt_desktop": "바탕화면 바로가기 생성",
        "wiz_opt_startmenu": "시작 메뉴 바로가기 및 Windows 제어판(앱 제거) 등록",
        "wiz_install_dir": "설치 폴더:",
        "wiz_browse": "변경...",
        "wiz_browse_title": "설치 폴더 선택",
        "wiz_prog_prep": "설치를 준비하고 있습니다...",
        "wiz_fin_title": "AI Usage Bar 설치가 완료되었습니다!",
        "wiz_fin_tip_title": "첫 사용 안내 (데이터가 바로 뜨게 하는 법)",
        "wiz_fin_tip_body": (
            "1. 데스크톱 앱 / 웹만 쓰셔도 위젯이 3분마다(또는 ↻ 클릭 시) 공식 CLI를 통해\n"
            "   사용량 차감 없이 Antigravity(일반·Argon)와 Claude(일반·Fable·5시간)를 자동 갱신합니다.\n"
            "2. 최초 1회만 각 CLI(agy, claude)에 구독 계정으로 로그인해 두시면 됩니다.\n"
            "   (Claude는 /login 에서 반드시 'Claude account with subscription' 선택)"
        ),
        "wiz_launch_after": "지금 AI Usage Bar 바로 실행하기",
        "wiz_err_title": "설치 오류",
        "wiz_err_hdr": "설치 중 오류가 발생했습니다.",
        "wiz_prog_start": "설치를 시작하는 중...",
        "wiz_err_no_payload": "설치 패키지를 찾을 수 없습니다: {path}",
        "wiz_step_stop": "실행 중인 기존 위젯 확인 및 종료...",
        "wiz_log_stop": "[1/6] 기존 실행 중인 AI Usage Bar 확인 중...",
        "wiz_step_extract": "프로그램 파일 압축 해제 중...",
        "wiz_log_dir": "[2/6] 설치 경로: {dir}",
        "wiz_prog_extract": "파일 압축 해제 중... ({cur}/{tot})",
        "wiz_log_extract_ok": "      앱 본체(AIUsageBar.exe) 및 초경량 네이티브 훅(quota_hook.exe) 설치 완료",
        "wiz_step_agy": "Antigravity CLI (agy) 설치 중...",
        "wiz_log_agy_run": "[3/6] Antigravity CLI (agy) 공식 설치 스크립트 실행 중...",
        "wiz_log_agy_ok": "      Antigravity CLI (agy) 설치/확인 완료",
        "wiz_log_agy_note": "      [안내] agy CLI 설치 중 메시지: {msg}",
        "wiz_log_agy_skip": "[3/6] Antigravity CLI (agy) 설치 건너뜀",
        "wiz_step_hooks": "공식 statusLine 훅 연결 중...",
        "wiz_log_hooks": "[4/6] 공식 statusLine 훅 연결 중...",
        "wiz_step_shortcuts": "바로가기 및 시작 프로그램 등록 중...",
        "wiz_log_shortcuts": "[5/6] 바로가기 및 자동 실행 설정 중...",
        "wiz_log_startup": "      Windows 시작 시 자동 실행: {state}",
        "wiz_log_desktop": "      바탕화면 바로가기 생성 완료",
        "wiz_log_startmenu": "      시작 메뉴 및 제어판 제거 항목 등록 완료",
        "wiz_uninst_lnk": "AI Usage Bar 제거.lnk",
        "wiz_uninst_desc": "AI Usage Bar 제거",
        "wiz_step_done": "설치 완료!",
        "wiz_log_done": "[6/6] 모든 설치 단계가 성공적으로 완료되었습니다.",
        "wiz_summary": "설치 위치: {dir}\n설치된 실행 파일: {exe} + quota_hook.exe",
        "wiz_log_err": "[오류] {exc}",
    },
    "en": {
        # HUD header & titles
        "hud_title_used": "AI Weekly Usage",
        "hud_title_rem": "AI Weekly Left",
        "tip_title": "Drag to move · Double-click to snap above taskbar",
        "tip_refresh_busy": "Refreshing...",
        "tip_refresh": "Refresh now (no quota deducted)",
        "tip_collapse": "Collapse to compact view",
        "tip_expand": "Expand details",
        "tip_settings": "Settings · Trends · Guide",
        "tip_pin_on": "Always on top (ON)",
        "tip_pin_off": "Always on top (OFF)",
        "tip_hide": "Hide to system tray",
        "tip_hide_macos": "Hide widget (click Dock icon to restore)",
        "tip_move_up": "Move up",
        "tip_move_dn": "Move down",

        # Compact / detail labels
        "waiting": "Waiting",
        "waiting_conn": "Waiting",
        "waiting_resp": "Pending",
        "waiting_resp_sp": "Pending",
        "reset_short": "Reset",
        "reset_done": "Reset",
        "reset_done_short": "Reset",
        "reset_tooltip": "Reset (quota refreshed)",
        "none_avail": "N/A",
        "cli_unavailable": "Not exposed",
        "after_first_chat": "After 1st reply",
        "days_7": "7d",
        "weekly_gen": "Weekly",
        "weekly_argon": "Argon Weekly",
        "weekly_fable": "Fable Weekly",
        "weekly_7d": "Weekly (7d)",
        "session_5h": "5h Session",
        "third_party_wk": "3P Weekly",
        "src_agy": "agy Auto",
        "src_cld_auto": "Auto Sync",
        "src_cld_hook": "Claude Hook",
        "src_cdx_log": "Session Log",
        "src_cdx_auto": "Codex Auto",
        "hint_agy": "Run `agy` once in terminal to sign in",
        "hint_cld": "Sign in to Claude Pro/Max via `/login`",
        "hint_cld_sync": "Claude Pro/Max auto sync",
        "hint_cdx": "Auto-reads Codex CLI / session logs",

        # Detail bottom bar
        "lbl_providers": "Providers",
        "lbl_compact": "Compact",
        "style_dual": "Dual",
        "style_slim": "Slim",
        "style_ring": "Ring",
        "style_dual_title": "Dual Line",
        "style_dual_sub": "Weekly + 5h together",
        "style_dual_desc": "Shows weekly bar and 5-hour session bar + countdown\naligned cleanly in two crisp rows.",
        "style_slim_title": "Slim Bar",
        "style_slim_sub": "Ultra-compact · 2-tier",
        "style_slim_desc": "Smallest height (99px) with stacked weekly + 5h bar.\nClick the right badge to toggle 5h ↔ model (Ar/Fb).",
        "style_ring_title": "Dual Ring",
        "style_ring_sub": "Outer=Weekly · Inner=5h",
        "style_ring_desc": "Anti-aliased concentric donut gauges: outer ring for\nweekly quota and inner ring for 5-hour session.",
        "btn_mode_used": "Mode: Used%",
        "btn_mode_rem": "Mode: Left%",
        "btn_snap": "Snap",
        "btn_settings_all": "⚙ Settings · Trends",

        # Context menu
        "menu_refresh": "Refresh Now",
        "menu_details": "Show Details",
        "menu_topmost": "Always on Top",
        "menu_snap": "Snap Above Taskbar",
        "menu_hide": "Hide to Tray",
        "menu_show": "Show Widget",
        "menu_trends": "Usage Trends / Pace",
        "menu_settings": "Settings · Hotkey · Guide...",
        "menu_quit": "Quit",

        # Tooltips & tray
        "mode_used_word": "Used",
        "mode_rem_word": "Left",
        "mode_basis": "{mode} %",
        "tip_pace": "Pace: {label}",
        "tip_note": "Hint: {msg}",
        "tip_updated_slim": "Updated: {age} · Click right: 5h↔Model",
        "tip_updated_dbl": "Updated: {age} · Double-click: Details",
        "tip_click_refresh": "Click ↻ to refresh · Double-click: Details",
        "tray_wk_prefix": "Wk",

        # Notifications
        "noti_test_title": "AI Usage Bar Test Alert",
        "noti_test_body": "Desktop notifications are working properly.",
        "noti_reset_title": "{label} Quota Reset",
        "noti_reset_body": "Your quota window has reset and is ready to use.",
        "noti_reset_new_body": "A fresh quota window has started.",
        "noti_crit_title": "{label} Critical ({pct:.0f}%)",
        "noti_crit_body": "Reached critical threshold ({th}%)",
        "noti_warn_title": "{label} Reached {pct:.0f}%",
        "noti_warn_body": "Warning threshold ({th}%) · {rem:.0f}% left",
        "noti_until_reset": "{cd} to reset",

        # Settings dialog
        "set_win_title": "AI Usage Bar Settings  v{ver}",
        "tab_display": "Display",
        "tab_alerts": "Alerts & Key",
        "tab_trends": "Trends",
        "tab_help": "Guide",
        "btn_open_data": "Open Data Folder",
        "btn_close": "Close",
        "sec_style_title": "Compact Style Preview",
        "sec_style_hint": "Click any card to apply live",
        "lbl_slim_sub": "Slim right-side badge:",
        "opt_slim_model": "Model (Ar·Fb)",
        "opt_slim_5h": "5h Session",
        "sec_order_title": "Providers & Order",
        "sec_order_hint": "Drag ⠿ up/down or use ▲/▼",
        "chip_shown": "Shown",
        "chip_hidden": "Hidden",
        "lbl_mode": "Display Mode",
        "lbl_pace_row": "Pace Tick (|) — Elapsed time on bar",
        "lbl_mode_and_pace": "Display Mode · Pace Tick",
        "chip_pace_marker": "Pace Tick |",
        "chip_used_pct": "Used %",
        "chip_rem_pct": "Left %",
        "lbl_theme": "Theme",
        "lbl_lang": "Lang",
        "lbl_theme_lang": "Theme · Language",
        "theme_auto": "Auto",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "lang_auto": "OS Auto",
        "lbl_opacity": "Widget Opacity",

        # Hotkey manager & refresher diagnostics
        "hk_macos_note": "macOS: ⌘R (Refresh) · ⌘, (Settings) · ⌘H (Hide) · ⌘Q (Quit) · Click Dock to restore",
        "hk_init_err": "Failed to initialize hotkey thread",
        "hk_disabled": "Hotkey disabled",
        "hk_invalid": "Unsupported shortcut format (e.g. Ctrl+Alt+Q)",
        "hk_in_use": "'{norm}' is already in use by another app.",
        "hk_registered": "Registered '{norm}'",
        "ref_agy_missing": "agy CLI not installed",
        "ref_agy_err": "agy launch error: {exc}",
        "ref_agy_ok": "Antigravity refreshed",
        "ref_agy_login": "Sign in required (run `agy` in terminal)",
        "ref_agy_timeout": "Antigravity refresh timed out",
        "ref_cld_missing": "Claude Code not installed",
        "ref_cld_trust": "No trusted Claude folder (run `claude` once)",
        "ref_cld_err": "Claude launch error: {exc}",
        "ref_cld_trust_once": "Trust folder once in Claude CLI",
        "ref_cld_login": "Claude Pro/Max sign-in required (/login)",
        "ref_cld_timeout": "No response from Claude /usage (check login)",
        "ref_cld_ok": "Claude refreshed",
        "ref_cdx_ok": "Codex refreshed",
        "ref_cdx_log_ok": "Loaded Codex session logs",
        "ref_cdx_missing": "Codex CLI not found or no session logs",

        "sec_alert_title": "Custom Usage Alerts",
        "btn_alert_test": "🔔 Test Alert",
        "chip_alert_on": "Alerts ON",
        "chip_alert_off": "Alerts OFF",
        "lbl_warn_th": "Warning threshold",
        "lbl_crit_th": "Critical threshold",
        "opt_off": "Off",
        "lbl_alert_scope": "Scope · Reset",
        "chip_on_reset": "Notify on Reset",
        "chip_scope_all": "Weekly + 5h",
        "chip_scope_wk": "Weekly Only",
        "sec_hotkey_title": "Global Hotkey (Show / Hide Widget)",
        "chip_on": "Enabled",
        "chip_off": "Off",
        "hk_recording": "Press key combo... (Esc cancel)",
        "hk_cancelled": "Shortcut recording cancelled.",
        "hk_hint": "e.g. Ctrl+Alt+Q, Ctrl+Shift+A, Alt+F9",
        "btn_hk_default": "Default",
        "btn_hk_cancel": "Cancel",
        "btn_hk_change": "Record Key",
        "lbl_refresh_iv": "Auto-refresh interval (pauses when idle)",
        "min_fmt": "{m}m",
        "chip_auto_refresh": "Auto Refresh",
        "chip_startup": "Start at Login",
        "btn_reconnect": "⚡ Reconnect Hooks",
        "btn_reconnected": "Reconnected ✓",

        "trends_legend": "Solid: Weekly  ·  Thin: 5h  ·  Dashed: Warn threshold",
        "period_24h": "24h",
        "period_7d": "7d",
        "pace_waiting": "Waiting for pace data",
        "trends_points": "{n} samples · Updated {age}",
        "trends_collecting": "Collecting data · Trend line builds automatically on each refresh",

        "help_c1_title": "1. Reading the HUD · Pace Tick (|) · Colors",
        "help_l1_k": "• Weekly (Top / Outer)",
        "help_l1_v": "7-day rolling usage (or remaining) percentage.",
        "help_l2_k": "• 5h (Bottom / Inner)",
        "help_l2_v": "5-hour short-term session limit & countdown.",
        "help_l3_k": "• Ar / Fb",
        "help_l3_v": "Antigravity Argon weekly · Claude Fable weekly buckets.",
        "help_l4_k": "• Vertical Tick (|)",
        "help_l4_v": "Elapsed time in the window. Shorter bar = relaxed, longer = fast!",
        "legend_ok": "Healthy (Brand)",
        "legend_warn": "Warning (75%+)",
        "legend_crit": "Critical ⚠ (90%+)",
        "legend_reset": "Reset",
        "help_c2_title": "2. Quick Shortcuts",
        "help_s1_k": "• Hover compact row/ring",
        "help_s1_v": "Shows remaining days/hours, exact reset time, and pace forecast.",
        "help_s2_k": "• Double-click row/ring",
        "help_s2_v": "Quickly expands details or collapses back to compact view.",
        "help_s3_k": "• Drag / Double-click title",
        "help_s3_v": "Drag anywhere to move; double-click to snap above taskbar.",
        "help_s4_k": "• Slim right-badge click",
        "help_s4_v": "In Slim mode, click the right badge to toggle 5h ↔ Ar/Fb.",
        "help_s5_k": "• Global Hotkey ({hk})",
        "help_s5_v": "Instantly show or hide the HUD from any app or fullscreen window.",
        "help_c3_title": "3. Zero-Deduction Auto Refresh & Sign-In",
        "help_c3_body": (
            "• Works even if you only use desktop/web apps: polls official CLIs in a hidden console with zero usage deducted.\n"
            "• Automatically pauses polling after 5 minutes of inactivity and resumes when you return.\n"
            "• Antigravity: run `agy` once in terminal and sign in with your Google account.\n"
            "• Claude: run `claude` → `/login` and select 'Claude account with subscription' (Pro/Max).\n"
            "• Codex (optional): install & sign in to `codex` CLI or let it read local session logs."
        ),

        # Uninstall dialog
        "uninst_title": "Uninstall AI Usage Bar",
        "uninst_confirm": (
            "Uninstall AI Usage Bar?\n\n"
            "- Stop running widget\n"
            "- Remove Claude Code / agy statusLine hooks\n"
            "- Remove startup entry and shortcuts"
        ),
        "uninst_done": "AI Usage Bar has been uninstalled.",

        # Installer Wizard
        "wiz_title": "AI Usage Bar Setup Wizard v{ver}",
        "wiz_header_sub": "  Setup Wizard  v{ver}",
        "wiz_step1": "1. Welcome",
        "wiz_step2": "2. Options",
        "wiz_step3": "3. Install",
        "wiz_step4": "4. Finish",
        "wiz_cancel": "Cancel",
        "wiz_back": "< Back",
        "wiz_next": "Next >",
        "wiz_start": "Install",
        "wiz_installing": "Installing...",
        "wiz_retry": "Retry",
        "wiz_done": "Finish",
        "wiz_welcome_h1": "Install AI Usage Bar for Antigravity · Claude · Codex",
        "wiz_welcome_sub": (
            "Monitor weekly (7-day) & short-term (5-hour) quotas, reset countdowns, and burn pace\n"
            "with an always-on-top mini floating HUD + native Windows system tray icon."
        ),
        "wiz_f1_t": "• No Python Required",
        "wiz_f1_d": "Includes standalone app binary and a 17 KB zero-dependency native statusLine hook.",
        "wiz_f2_t": "• Auto-Refresh Even for Web/Desktop App Users",
        "wiz_f2_d": "Silently queries official CLIs with zero quota deducted, pausing automatically when idle.",
        "wiz_f3_t": "• 3 Compact Styles with Live Previews & Drag-to-Reorder",
        "wiz_f3_d": "Pick Dual, Slim, or Dual-Ring styles with visual previews and drag to reorder providers.",
        "wiz_f4_t": "• Pace Marker · Trend Charts · Custom Alerts & Hotkey · EN/KO",
        "wiz_f4_d": "Includes elapsed-time pace tick (|), 24h/7d trends, custom alert thresholds, and English/Korean UI.",
        "wiz_welcome_foot": "Click [Next >] to check installed CLIs and choose your setup options.",
        "wiz_env_title": "Detected CLI Environment",
        "wiz_detected": "Detected ✓",
        "wiz_not_found_claude": "Not found (hooks still configured for later)",
        "wiz_not_found_agy": "Not found (optional auto-install below)",
        "wiz_not_found_codex": "Not found (optional, toggle below)",
        "wiz_show_ai": "Providers to show:",
        "wiz_opt_title": "Integration & Install Options",
        "wiz_opt_claude": "Connect Claude Code official statusLine (backs up ~/.claude/settings.json)",
        "wiz_opt_agy": "Connect Antigravity CLI (agy) official statusLine",
        "wiz_opt_agy_inst_done": "Run official Antigravity CLI (agy) installer (already installed)",
        "wiz_opt_agy_inst_rec": "Run official Antigravity CLI (agy) installer (recommended)",
        "wiz_opt_startup": "Launch AI Usage Bar automatically when Windows starts",
        "wiz_opt_desktop": "Create Desktop shortcut",
        "wiz_opt_startmenu": "Create Start Menu shortcuts & register Windows Apps uninstall entry",
        "wiz_install_dir": "Install folder:",
        "wiz_browse": "Browse...",
        "wiz_browse_title": "Choose Install Folder",
        "wiz_prog_prep": "Preparing installation...",
        "wiz_fin_title": "AI Usage Bar is Ready!",
        "wiz_fin_tip_title": "Quick Start Guide",
        "wiz_fin_tip_body": (
            "1. Even if you only use desktop/web apps, the HUD refreshes every 3 min (or on ↻ click)\n"
            "   via official CLIs with zero quota deducted.\n"
            "2. Sign in once to each CLI you use (`agy`, `claude`).\n"
            "   (For Claude, run `/login` and choose 'Claude account with subscription'.)"
        ),
        "wiz_launch_after": "Launch AI Usage Bar now",
        "wiz_err_title": "Installation Error",
        "wiz_err_hdr": "An error occurred during installation.",
        "wiz_prog_start": "Starting installation...",
        "wiz_err_no_payload": "Installer payload not found: {path}",
        "wiz_step_stop": "Checking and stopping existing widget...",
        "wiz_log_stop": "[1/6] Checking for running AI Usage Bar instances...",
        "wiz_step_extract": "Extracting application files...",
        "wiz_log_dir": "[2/6] Install folder: {dir}",
        "wiz_prog_extract": "Extracting files... ({cur}/{tot})",
        "wiz_log_extract_ok": "      Installed AIUsageBar.exe and lightweight native hook (quota_hook.exe)",
        "wiz_step_agy": "Installing Antigravity CLI (agy)...",
        "wiz_log_agy_run": "[3/6] Running official Antigravity CLI (agy) installer...",
        "wiz_log_agy_ok": "      Antigravity CLI (agy) installed/verified",
        "wiz_log_agy_note": "      [Note] agy installer output: {msg}",
        "wiz_log_agy_skip": "[3/6] Skipped Antigravity CLI (agy) installation",
        "wiz_step_hooks": "Connecting official statusLine hooks...",
        "wiz_log_hooks": "[4/6] Configuring official statusLine hooks...",
        "wiz_step_shortcuts": "Creating shortcuts and startup entry...",
        "wiz_log_shortcuts": "[5/6] Configuring shortcuts and login startup...",
        "wiz_log_startup": "      Launch at Windows login: {state}",
        "wiz_log_desktop": "      Desktop shortcut created",
        "wiz_log_startmenu": "      Start Menu shortcuts & Apps uninstall entry registered",
        "wiz_uninst_lnk": "Uninstall AI Usage Bar.lnk",
        "wiz_uninst_desc": "Uninstall AI Usage Bar",
        "wiz_step_done": "Installation complete!",
        "wiz_log_done": "[6/6] All installation steps completed successfully.",
        "wiz_summary": "Install location: {dir}\nInstalled binaries: {exe} + quota_hook.exe",
        "wiz_log_err": "[Error] {exc}",
    },
}


def tr(lang: str, key: str, **kwargs: object) -> str:
    """Translate `key` into effective language ('ko' or 'en') with optional format kwargs."""
    eff = "ko" if lang == "ko" else "en"
    table = STRINGS[eff]
    raw = table.get(key, STRINGS["en"].get(key, key))
    if kwargs:
        try:
            return raw.format(**kwargs)
        except Exception:
            return raw
    return raw
