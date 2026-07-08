#!/usr/bin/env python3
"""
基估宝 · 基金日报
===============
每天 4 次获取基金实时估值，生成 HTML 邮件发送。
触发时间（北京时间）：10:00 / 12:00 / 14:30 / 16:00

数据来源：
  基金实时估值 — fundgz.1234567.com.cn (天天基金)
  大盘指数     — qt.gtimg.cn (腾讯行情)
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

# ── 时区 ────────────────────────────────────────────────
CST = timezone(timedelta(hours=8))


def now_cst():
    return datetime.now(CST)


def fmt_pct(val):
    """格式化百分比，正数带+号"""
    try:
        v = float(val)
        if v > 0:
            return f"+{v:.2f}%"
        elif v < 0:
            return f"{v:.2f}%"
        else:
            return "0.00%"
    except (TypeError, ValueError):
        return "—"


def fmt_price(val):
    """格式化净值"""
    try:
        return f"{float(val):.4f}"
    except (TypeError, ValueError):
        return "—"


# ═══════════════════════════════════════════════════════════
# 基金列表（从基估宝 localStorage 导出）
# ═══════════════════════════════════════════════════════════
FUNDS = [
    ("159363", "创业板人工智能ETF华宝"),
    ("018816", "方正富邦核心优势混合C"),
    ("010034", "安信成长精选混合C"),
    ("005091", "嘉合睿金混合发起式C"),
    ("017437", "华宝纳斯达克精选股票发起式(QDII)C"),
    ("021662", "国富亚洲机会股票(QDII)C"),
    ("016874", "广发远见智选混合C"),
    ("012922", "易方达全球成长精选混合(QDII)人民币C"),
    ("015454", "中欧中证500指数增强C"),
    ("017730", "嘉实全球产业升级股票发起式(QDII)A"),
    ("023895", "天弘上证科创板综合指数增强A"),
    ("019889", "中欧周期优选混合发起C"),
    ("018463", "德邦稳盈增长灵活配置混合C"),
    ("016371", "信澳业绩驱动混合C"),
    ("022365", "永赢科技智选混合发起C"),
    ("018363", "东方阿尔法瑞丰混合发起C"),
    ("007413", "长城中证500指数增强C"),
    ("002112", "德邦鑫星价值灵活配置混合C"),
    ("006533", "易方达科融混合"),
    ("009982", "万家创业板指数增强C"),
    ("025209", "永赢先锋半导体智选混合发起C"),
]

# 大盘指数
MARKET_INDICES = [
    ("sh000001", "上证"),
    ("sz399001", "深证"),
    ("sh000300", "沪深300"),
    ("sh000688", "科创50"),
    ("sz399006", "创业板"),
]

# ═══════════════════════════════════════════════════════════
# SMTP 配置
# ═══════════════════════════════════════════════════════════
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = "zwj1994522@qq.com"
RECIPIENT = os.environ.get("RECIPIENT", "zwj1994522@qq.com")

# GitHub Secrets 中设置
SMTP_AUTH_CODE = os.environ.get("SMTP_AUTH_CODE", "")

# ═══════════════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════════════

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_fund_valuation(code, retries=2):
    """
    从天天基金获取单只基金实时估值。
    返回 dict 或 None。
    """
    url = f"https://fundgz.1234567.com.cn/js/{code}.js"
    for attempt in range(retries):
        try:
            resp = requests.get(
                url, timeout=10,
                headers={"User-Agent": UA, "Referer": "https://fundf10.eastmoney.com/"}
            )
            resp.encoding = "utf-8"
            text = resp.text
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                if attempt < retries - 1:
                    continue
                return {"code": code, "error": "响应格式异常"}

            data = json.loads(m.group())
            return {
                "code": data.get("fundcode", code),
                "name": data.get("name", ""),
                "dwjz": data.get("dwjz", ""),
                "gsz": data.get("gsz", ""),
                "gszzl": data.get("gszzl", ""),
                "gztime": data.get("gztime", ""),
                "jzrq": data.get("jzrq", ""),
            }
        except requests.Timeout:
            if attempt < retries - 1:
                continue
            return {"code": code, "error": "请求超时"}
        except Exception as e:
            if attempt < retries - 1:
                continue
            return {"code": code, "error": str(e)}
    return {"code": code, "error": "未知错误"}


def fetch_all_funds():
    """批量获取所有基金估值，请求间加短暂延迟"""
    results = []
    for code, _ in FUNDS:
        data = fetch_fund_valuation(code)
        results.append(data)
    return results


def fetch_market_indices():
    """从腾讯行情获取大盘指数"""
    codes = ",".join(c for c, _ in MARKET_INDICES)
    url = f"https://qt.gtimg.cn/q={codes}"
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": UA, "Referer": "https://finance.qq.com"}
        )
        resp.encoding = "gbk"
        text = resp.text

        results = []
        for code, name in MARKET_INDICES:
            var_name = f"v_{code}"
            pattern = re.compile(re.escape(var_name) + r'="([^"]*)"')
            m = pattern.search(text)
            if m:
                parts = m.group(1).split("~")
                if code.startswith(("us", "hk", "gz")):
                    # 海外指数: ~name~price~change~pct~
                    results.append({
                        "name": name,
                        "price": float(parts[3]) if len(parts) > 3 and parts[3] else None,
                        "change": float(parts[4]) if len(parts) > 4 and parts[4] else None,
                        "pct": float(parts[5]) if len(parts) > 5 and parts[5] else None,
                    })
                elif len(parts) >= 33:
                    results.append({
                        "name": name,
                        "price": float(parts[3]) if parts[3] else None,
                        "change": float(parts[31]) if parts[31] else None,
                        "pct": float(parts[32]) if parts[32] else None,
                    })
                else:
                    results.append({"name": name, "price": None, "change": None, "pct": None})
            else:
                results.append({"name": name, "price": None, "change": None, "pct": None})
        return results
    except Exception as e:
        print(f"[WARN] 大盘指数获取失败: {e}", file=sys.stderr)
        return [{"name": name, "price": None, "change": None, "pct": None} for _, name in MARKET_INDICES]


# ═══════════════════════════════════════════════════════════
# HTML 报告生成
# ═══════════════════════════════════════════════════════════

def _color(val):
    """红涨绿跌灰平"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "#999"
    if v > 0:
        return "#e74c3c"  # 红
    elif v < 0:
        return "#27ae60"  # 绿
    return "#999"


def _bg(val):
    """行背景色"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "transparent"
    if v > 0:
        return "#fff5f5"
    elif v < 0:
        return "#f0faf4"
    return "transparent"


def build_html(funds_data, indices, ts):
    """生成 HTML 邮件正文"""

    # ── 汇总统计 ──
    valid = [f for f in funds_data if "gszzl" in f and f["gszzl"] != "" and f.get("error") is None]
    gains = []
    for f in valid:
        try:
            gains.append(float(f["gszzl"]))
        except (ValueError, TypeError):
            pass

    up = sum(1 for g in gains if g > 0)
    down = sum(1 for g in gains if g < 0)
    flat = len(gains) - up - down
    avg_gain = sum(gains) / len(gains) if gains else 0
    best = max(valid, key=lambda f: float(f.get("gszzl", -999))) if valid else None
    worst = min(valid, key=lambda f: float(f.get("gszzl", 999))) if valid else None
    error_funds = [f for f in funds_data if f.get("error")]
    no_est = [f for f in funds_data if f.get("gszzl", "") == "" and f.get("error") is None]

    # ── 大盘指数行 ──
    idx_rows = ""
    for idx in indices:
        p = idx.get("pct")
        if p is not None:
            clr = _color(p)
            p_str = f"{p:+.2f}%"
        else:
            clr = "#999"
            p_str = "—"

        pr = idx.get("price")
        pr_str = f"{pr:.2f}" if pr is not None else "—"

        idx_rows += (
            f'<span style="margin-right:24px;font-size:14px">'
            f'<b>{idx["name"]}</b> '
            f'<span style="color:#333">{pr_str}</span> '
            f'<span style="color:{clr};font-weight:600">{p_str}</span>'
            f'</span>'
        )

    # ── 基金表格 ──
    rows = ""
    # 按估算涨幅降序排列
    sorted_funds = sorted(
        funds_data,
        key=lambda f: float(f.get("gszzl", -99)) if f.get("gszzl", "") != "" else -99,
        reverse=True
    )

    for i, f in enumerate(sorted_funds):
        e = f.get("error")
        if e:
            rows += (
                f'<tr style="background:#fffbf0">'
                f'<td style="color:#999">{i+1}</td>'
                f'<td>{f["code"]}</td>'
                f'<td style="color:#999">获取失败</td>'
                f'<td colspan="4" style="color:#e67e22;font-size:12px">{e}</td>'
                f'</tr>'
            )
            continue

        gszzl = f.get("gszzl", "")
        clr = _color(gszzl)
        bg = _bg(gszzl)
        gszzl_str = fmt_pct(gszzl) if gszzl != "" else '<span style="color:#999">暂无</span>'

        rows += (
            f'<tr style="background:{bg}">'
            f'<td style="color:#999;text-align:center">{i+1}</td>'
            f'<td style="font-family:monospace">{f["code"]}</td>'
            f'<td style="max-width:180px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">{f.get("name","")}</td>'
            f'<td style="text-align:right;font-family:monospace">{fmt_price(f.get("dwjz"))}</td>'
            f'<td style="text-align:right;font-family:monospace">{fmt_price(f.get("gsz"))}</td>'
            f'<td style="text-align:right;font-weight:700;color:{clr};font-size:15px">{gszzl_str}</td>'
            f'<td style="color:#999;font-size:11px;text-align:center">{f.get("gztime","—")}</td>'
            f'</tr>'
        )

    # ── 备注 ──
    notes = []
    if error_funds:
        codes = ", ".join(f["code"] for f in error_funds)
        notes.append(f"⚠ 获取失败: {codes}")
    if no_est:
        codes = ", ".join(f["code"] for f in no_est)
        notes.append(f"📌 暂无实时估值（可能为 QDII 或非交易时段）: {codes}")
    if not gains:
        notes.append("💤 当前无有效估值数据，可能为非交易日。")

    notes_html = "".join(
        f'<div style="margin-top:4px;font-size:13px;color:#888">{n}</div>' for n in notes
    ) if notes else ""

    # ── 完整 HTML ──
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekday_names[ts.weekday()]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f6fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6fa;padding:20px 0">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.06)">

<!-- 头部 -->
<tr>
  <td style="padding:28px 32px 20px;background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%)">
    <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:4px">
      📊 基估宝 · 基金日报
    </div>
    <div style="font-size:13px;color:rgba(255,255,255,0.7)">
      {ts.strftime('%Y年%m月%d日')} 星期{wd} · 报告时间 {ts.strftime('%H:%M')} (北京时间)
    </div>
  </td>
</tr>

<!-- 大盘指数 -->
<tr>
  <td style="padding:16px 32px;border-bottom:1px solid #f0f0f0;background:#fafbfc">
    <div style="font-size:12px;color:#999;margin-bottom:6px">大盘指数</div>
    <div>{idx_rows}</div>
  </td>
</tr>

<!-- 汇总卡片 -->
<tr>
  <td style="padding:20px 32px;border-bottom:1px solid #f0f0f0">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="25%" style="text-align:center">
          <div style="font-size:11px;color:#999;margin-bottom:2px">基金数量</div>
          <div style="font-size:22px;font-weight:700;color:#333">{len(funds_data)}</div>
        </td>
        <td width="25%" style="text-align:center">
          <div style="font-size:11px;color:#999;margin-bottom:2px">上涨 / 下跌</div>
          <div style="font-size:22px;font-weight:700">
            <span style="color:#e74c3c">{up}</span>
            <span style="color:#ccc">/</span>
            <span style="color:#27ae60">{down}</span>
          </div>
        </td>
        <td width="25%" style="text-align:center">
          <div style="font-size:11px;color:#999;margin-bottom:2px">平均涨幅</div>
          <div style="font-size:22px;font-weight:700;color:{_color(avg_gain)}">{fmt_pct(avg_gain)}</div>
        </td>
        <td width="25%" style="text-align:center">
          <div style="font-size:11px;color:#999;margin-bottom:2px">平盘</div>
          <div style="font-size:22px;font-weight:700;color:#999">{flat}</div>
        </td>
      </tr>
      <tr><td colspan="4" style="padding-top:12px">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td width="50%" style="font-size:13px">
              🔥 最佳: <b style="color:#e74c3c">{best['code']} {best.get('name','')[:8]}</b>
              <span style="color:#e74c3c;font-weight:700"> {fmt_pct(best.get('gszzl',''))}</span>
            </td>
            <td width="50%" style="font-size:13px">
              ❄️ 最差: <b style="color:#27ae60">{worst['code']} {worst.get('name','')[:8]}</b>
              <span style="color:#27ae60;font-weight:700"> {fmt_pct(worst.get('gszzl',''))}</span>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </td>
</tr>

<!-- 基金明细表格 -->
<tr>
  <td style="padding:8px 32px 24px">
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px">
      <thead>
        <tr style="border-bottom:2px solid #e8e8e8">
          <th style="padding:8px 4px;text-align:center;color:#999;font-weight:500;font-size:11px">#</th>
          <th style="padding:8px 4px;text-align:left;color:#999;font-weight:500;font-size:11px">代码</th>
          <th style="padding:8px 4px;text-align:left;color:#999;font-weight:500;font-size:11px">名称</th>
          <th style="padding:8px 4px;text-align:right;color:#999;font-weight:500;font-size:11px">单位净值</th>
          <th style="padding:8px 4px;text-align:right;color:#999;font-weight:500;font-size:11px">估算净值</th>
          <th style="padding:8px 4px;text-align:right;color:#999;font-weight:500;font-size:11px">估算涨幅</th>
          <th style="padding:8px 4px;text-align:center;color:#999;font-weight:500;font-size:11px">估值时间</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
    {notes_html}
  </td>
</tr>

<!-- 页脚 -->
<tr>
  <td style="padding:16px 32px;background:#fafbfc;border-top:1px solid #f0f0f0;text-align:center">
    <div style="font-size:11px;color:#bbb">
      数据来源: 天天基金 (fundgz.1234567.com.cn) · 大盘指数: 腾讯行情<br>
      估值数据可能存在偏差，仅供参考，不构成投资建议。<br>
      Generated by GitHub Actions
    </div>
  </td>
</tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
# 邮件发送
# ═══════════════════════════════════════════════════════════

def send_email(html_body, ts):
    """通过 QQ SMTP 发送 HTML 邮件"""
    if not SMTP_AUTH_CODE:
        print("[ERROR] 未设置 SMTP_AUTH_CODE 环境变量，跳过发送", file=sys.stderr)
        return False

    subject = f"📊 基金日报 — {ts.strftime('%m/%d')} {ts.strftime('%H:%M')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT

    # 纯文本备选
    plain = f"基金日报 {ts.strftime('%Y-%m-%d %H:%M')}\n请使用支持 HTML 的邮件客户端查看。"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15)
        server.login(SMTP_USER, SMTP_AUTH_CODE)
        server.sendmail(SMTP_USER, [RECIPIENT], msg.as_string())
        server.quit()
        print(f"[OK] 邮件已发送 → {RECIPIENT}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[ERROR] SMTP 认证失败，请检查 QQ 邮箱授权码是否正确", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main():
    ts = now_cst()
    print(f"═══ 基金日报 {ts.strftime('%Y-%m-%d %H:%M:%S')} CST ═══")

    # 1. 获取基金估值
    print(f"[1/3] 正在获取 {len(FUNDS)} 只基金估值...")
    funds_data = fetch_all_funds()
    ok_count = sum(1 for f in funds_data if f.get("error") is None)
    print(f"      成功: {ok_count}/{len(FUNDS)}")

    # 2. 获取大盘指数
    print("[2/3] 正在获取大盘指数...")
    indices = fetch_market_indices()
    print(f"      获取 {len(indices)} 个指数")

    # 3. 生成并发送邮件
    print("[3/3] 生成报告并发送...")
    html = build_html(funds_data, indices, ts)

    # GitHub Actions 环境：输出 HTML 到文件便于调试
    if os.environ.get("GITHUB_ACTIONS"):
        with open("fund_report.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("      报告已保存至 fund_report.html")

    success = send_email(html, ts)
    if not success and not SMTP_AUTH_CODE:
        # 本地测试：保存 HTML 到文件
        path = "fund_report_preview.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[INFO] 未配置 SMTP，报告已保存至 {path}，可在浏览器中预览")

    print("═══ 完成 ═══")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
