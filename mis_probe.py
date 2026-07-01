"""
THROWAWAY diagnostic. Proves whether the GitHub Actions runner can reach
TWSE MIS (mis.twse.com.tw/stock/api/getStockInfo.jsp) at all, and if so,
what request recipe it needs. Manual-trigger only. Delete after we read it.

Tries two ways:
  A) bare call            -- simplest possible GET
  B) warmup + UA + Referer -- visit MIS first to pick up a session cookie,
                              then call with a browser-style User-Agent.
Prints a loud PROBE RESULT line at the end. Always exits 0 so the run shows
green and the log is easy to read regardless of outcome.
"""
import time
import requests

# one TWSE (tse_) + one TPEx (otc_) so we prove BOTH exchanges resolve.
TICKERS = "tse_2330.tw|tse_2317.tw|otc_6488.tw"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def call(sess, label, warmup=False):
    print(f"\n--- attempt {label} ---")
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if warmup:
        headers["Referer"] = "https://mis.twse.com.tw/stock/fibest.jsp?stock=2330"
        try:
            w = sess.get("https://mis.twse.com.tw/stock/index.jsp",
                         headers={"User-Agent": UA}, timeout=15)
            print(f"warmup GET index.jsp -> HTTP {w.status_code}; "
                  f"cookies now = {list(sess.cookies.keys())}")
        except Exception as e:
            print(f"warmup GET failed: {e!r}")

    url = (f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?"
           f"ex_ch={TICKERS}&json=1&delay=0&_={int(time.time() * 1000)}")
    try:
        r = sess.get(url, headers=headers, timeout=20)
    except Exception as e:
        print(f"REQUEST FAILED (network error / blocked): {e!r}")
        return False

    print(f"HTTP {r.status_code}; {len(r.content)} bytes; "
          f"content-type={r.headers.get('content-type')}")
    body = (r.text or "").strip()
    if not body:
        print("EMPTY BODY  (classic 'no session cookie' symptom)")
        return False
    try:
        j = r.json()
    except Exception:
        print(f"NON-JSON body (first 200 chars): {body[:200]!r}")
        return False

    arr = j.get("msgArray") or []
    print(f"rtcode={j.get('rtcode')} rtmessage={j.get('rtmessage')!r} "
          f"msgArray_len={len(arr)}")
    for row in arr:
        print(f"   {row.get('c')} {row.get('n')}: "
              f"last(z)={row.get('z')} prevClose(y)={row.get('y')} "
              f"cumVol(v)={row.get('v')} "
              f"ask5(a)={str(row.get('a'))[:26]} "
              f"bid5(b)={str(row.get('b'))[:26]} tlong={row.get('tlong')}")
    return len(arr) > 0


def main():
    print("=== MIS reachability probe ===")
    ok_bare = call(requests.Session(), "A: bare call")
    ok_warm = call(requests.Session(), "B: warmup + UA + Referer", warmup=True)

    print("\n" + "=" * 44)
    if ok_bare or ok_warm:
        recipe = "bare call works" if ok_bare else "needs session warmup + Referer"
        print("PROBE RESULT: MIS REACHABLE FROM ACTIONS  \u2705")
        print(f"   recipe: {recipe}")
        print("   => Option B is viable. Proceed to build feeder_intraday.")
    else:
        print("PROBE RESULT: MIS NOT REACHABLE / BLOCKED FROM ACTIONS  \u274c")
        print("   => Fall back to Option A (own Cloudflare Worker proxy).")
    print("=" * 44)


if __name__ == "__main__":
    main()
