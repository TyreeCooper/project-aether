(function(){
  const TTL={ "/api/v1/floor":4000, "/api/v1/settings":15000, "/api/v1/desk/blotter":6000 };
  const mem=new Map();
  const orig=window.fetch;
  window.fetch=function(input,init){
    const url=typeof input==="string"?input:(input&&input.url)||"";
    const method=(init&&init.method)||"GET";
    if(document.hidden && method==="GET" && url.indexOf("/api/")===0){
      const hit=mem.get(url.split("?")[0]);
      if(hit) return Promise.resolve(new Response(JSON.stringify(hit.body),{headers:{"Content-Type":"application/json"}}));
    }
    if(method==="GET"){
      const key=url.split("?")[0];
      const ttl=TTL[key] || (key.indexOf("/api/v1/assets/")===0?3000:0);
      const hit=mem.get(key);
      if(ttl && hit && Date.now()-hit.at<ttl){
        return Promise.resolve(new Response(JSON.stringify(hit.body),{headers:{"Content-Type":"application/json"}}));
      }
    }
    return orig(input,init).then(res=>{
      if(method==="GET" && res.ok){
        const key=url.split("?")[0];
        res.clone().json().then(body=>mem.set(key,{at:Date.now(),body})).catch(()=>{});
      }
      return res;
    });
  };
})();
