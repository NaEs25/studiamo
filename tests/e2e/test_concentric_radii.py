"""
Nested corners are concentric (macOS 26 / iOS 26 style): an element sitting close to a rounded
parent's corner has radius = parent radius minus the gap between them, never below the 6px chip
radius. Measured on the rendered goals tab with every hidden dialog forced visible, so a class
change that breaks the rule inside a modal or card fails here. Elements clipped flush by their
parent (radius 0, overflow hidden) and the iOS install-guide mock phone are exempt.
"""
JS = """
() => {
  const out=[]; const vis=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return r.width>4&&r.height>4&&s.display!=='none'&&s.visibility!=='hidden'&&r.bottom>0};
  const rad=e=>{const s=getComputedStyle(e);const v=[s.borderTopLeftRadius,s.borderTopRightRadius,s.borderBottomRightRadius,s.borderBottomLeftRadius].map(parseFloat);return v.every(x=>x===v[0])?v[0]:null};
  const painted=e=>{const s=getComputedStyle(e);return (s.backgroundColor!=='rgba(0, 0, 0, 0)')||parseFloat(s.borderTopWidth)>0};
  for(const e of document.querySelectorAll('body *')){
    if(!vis(e)) continue; const r=rad(e); if(r===null) continue; if(!(r>0||painted(e))) continue;
    const rr=e.getBoundingClientRect(); if(r>=Math.min(rr.width,rr.height)/2-0.5 && r>0) continue;
    let p=e.parentElement; while(p&&!(rad(p)>0&&painted(p))) p=p.parentElement; if(!p) continue;
    const R=rad(p); const pr=p.getBoundingClientRect(); if(R>=Math.min(pr.width,pr.height)/2-0.5) continue;
    const bw=parseFloat(getComputedStyle(p).borderTopWidth)||0;
    const inset=Math.min(rr.left-pr.left,rr.top-pr.top,pr.right-rr.right,pr.bottom-rr.bottom)-bw;
    if(inset>=12||inset<0||r===0||p.closest('.ios-anim-phone')) continue;
    const exp=Math.max(R-inset,6);
    if(Math.abs(r-exp)>2.5) out.push({cls:(e.className||'').toString().slice(0,90),tag:e.tagName,r,R,inset:Math.round(inset),exp:Math.round(exp),pcls:(p.className||'').toString().slice(0,60)});
  }
  return out;
}
"""
def test_nested_corners_are_concentric(goals_page):
    page = goals_page
    page.set_viewport_size({"width": 430, "height": 900})
    page.add_style_tag(content=".hidden{display:block !important} [class*='fixed']{position:relative !important;inset:auto !important}")
    page.wait_for_timeout(500)
    bad = page.evaluate(JS)
    assert bad == [], bad
