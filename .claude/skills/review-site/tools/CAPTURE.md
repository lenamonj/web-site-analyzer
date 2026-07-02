# Browser capture reference (rendered DOM, web vitals, contrast)

The scanners are stdlib-only and never launch a browser. The agent's browser
pass produces two artifacts per reviewed site under
`planning/_evidence/rendered/<slug>/`; the next `scan_site.py` run consumes
them automatically. All numbers are lab measurements of one page load and are
reported as such.

## 1. Rendered DOM snapshots (feeds the structural scanners)

For each page the scan flagged `likely_client_rendered`: load it, dismiss any
cookie or region overlay, then capture:

```js
document.documentElement.outerHTML
```

Write one file per page plus the manifest:

```
planning/_evidence/rendered/<slug>/<name>.html
planning/_evidence/rendered/<slug>/manifest.json
```

```json
{
  "captured_with": "<tool name>",
  "viewport": "1440px",
  "pages": {
    "<exact page url as scanned>": {
      "file": "<name>.html",
      "captured_at_utc": "2026-07-03T00:00:00Z"
    }
  }
}
```

## 2. Web vitals and contrast (feeds scan_vitals)

Run in the loaded page after network idle. Collects LCP, CLS (excluding
shifts after recent input), and TBT (long tasks minus 50 ms each, load
window only):

```js
(async () => {
  const byType = t => new Promise(res => {
    const es = [];
    const o = new PerformanceObserver(l => es.push(...l.getEntries()));
    try { o.observe({type: t, buffered: true}); } catch (e) {}
    setTimeout(() => { o.disconnect(); res(es); }, 400);
  });
  const lcp = (await byType('largest-contentful-paint')).pop();
  const shifts = await byType('layout-shift');
  const longtasks = await byType('longtask');
  const cls = shifts.filter(s => !s.hadRecentInput).reduce((a, s) => a + s.value, 0);
  const tbt = longtasks.reduce((a, t) => a + Math.max(0, t.duration - 50), 0);
  return {
    lcp_ms: lcp ? Math.round(lcp.startTime) : null,
    cls: Math.round(cls * 1000) / 1000,
    tbt_ms: Math.round(tbt)
  };
})()
```

Contrast (WCAG 1.4.3, computed styles - the axe-core approach). Samples
visible text nodes, resolves the effective background, and reports elements
below their required ratio (4.5:1 normal text, 3:1 large text):

```js
(() => {
  const lum = c => {
    const [r, g, b] = c.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number)
      .map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const bgOf = el => {
    for (let e = el; e; e = e.parentElement) {
      const bg = getComputedStyle(e).backgroundColor;
      if (bg && !bg.includes('rgba(0, 0, 0, 0)')) return bg;
    }
    return 'rgb(255, 255, 255)';
  };
  const out = {checked: 0, violations: []};
  for (const el of document.querySelectorAll('body *')) {
    if (!el.innerText || !el.innerText.trim() || el.children.length) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    out.checked++;
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const required = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    const l1 = lum(cs.color), l2 = lum(bgOf(el));
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    if (ratio < required) out.violations.push({
      sample: el.innerText.trim().slice(0, 40),
      ratio: Math.round(ratio * 100) / 100,
      required
    });
    if (out.violations.length >= 25) break;
  }
  return out;
})()
```

Write the combined result:

```
planning/_evidence/rendered/<slug>/metrics.json
```

```json
{
  "captured_with": "<tool name>",
  "viewport": "1440px",
  "pages": {
    "<exact page url as scanned>": {
      "lcp_ms": 1840, "cls": 0.04, "tbt_ms": 120,
      "contrast": {"checked": 210, "violations": []},
      "captured_at_utc": "2026-07-03T00:00:00Z"
    }
  }
}
```

Notes:
- The page url keys must match the scanned urls exactly.
- Set a metric to null when its API produced nothing; scan_vitals reports it
  as not captured instead of guessing.
- The computed-style contrast walk is a sample, not a proof: gradients,
  images under text, and pseudo-elements are not resolved. Verdicts say
  "sampled".
