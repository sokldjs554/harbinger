"use strict";
(() => {
  const definitions = [
    ["위치로 설비 찾기", "진행자가 정한 층·구역의 설비를 찾고 ID를 확인합니다."],
    ["원문과 점검 날짜 읽기", "점검 메모와 작성 날짜를 찾고 현재 수리 완료 여부를 알 수 있는지 말합니다."],
    ["예측 당시와 이후 결과 구분하기", "예측 기준일과 이후 30일 결과를 자신의 말로 설명합니다."],
    ["조건을 바꾸고 계산하기", "기준일·고객사를 바꾸고 적용 전후 차이를 확인합니다."],
    ["정상 CSV 불러오기", "합성 예제 CSV를 올립니다. 기록 완전성을 모르는 경우 확인란을 어떻게 처리할지 설명합니다. 저장 재생 환경이면 미실시로 남깁니다."],
    ["오류를 읽고 복구하기", "복사본의 overall을 9로 바꾼 오류 파일을 올리고 안내를 따라 수정합니다. 저장 재생 환경이면 미실시로 남깁니다."],
    ["내보낸 결과 확인하기", "결과를 내려받아 적용 기준일·고객사·모델 버전을 확인합니다."]
  ];
  const $ = id => document.getElementById(id);
  const states = {active:"진행 중",waiting:"시스템 대기 표시",paused:"중단",finished:"기록 종료",pending:"미실시"};
  const tasks = definitions.map((d,i)=>({id:i+1,title:d[0],events:[],result:null,help:"",notes:"",state:"pending",origin:null}));
  let running = null;
  const day = new Date();
  $("date").value = `${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,"0")}-${String(day.getDate()).padStart(2,"0")}`;
  function element(tag, text, attrs={}) {
    const el=document.createElement(tag); if(text!==null) el.textContent=text;
    for(const [k,v] of Object.entries(attrs)) el.setAttribute(k,v); return el;
  }
  function sum(task, now=false) {
    const total={active_ms:0,waiting_ms:0,paused_ms:0}, events=task.events.slice();
    if(now && running===task.id) events.push({state:"current",at_ms:Math.round(performance.now()-task.origin)});
    for(let i=1;i<events.length;i++) total[events[i-1].state+"_ms"]+=events[i].at_ms-events[i-1].at_ms;
    return total;
  }
  function clock(n){return (n/1000).toFixed(1)+"초";}
  function refresh() {
    for(const task of tasks) {
      const box=document.querySelector(`[data-task="${task.id}"]`), active=running===task.id, done=task.state==="finished";
      box.classList.toggle("running",active);
      box.querySelector(".status").textContent=done ? (task.result==="not_attempted" ? "미실시로 기록" : "기록 종료") : states[task.state];
      const t=sum(task,true); box.querySelector(".clock").textContent=`조작 ${clock(t.active_ms)} · 대기 표시 ${clock(t.waiting_ms)} · 중단 ${clock(t.paused_ms)}`;
      for(const button of box.querySelectorAll("[data-action]")) {
        const a=button.dataset.action;
        button.disabled=(a==="start"||a==="skip") ? running!==null||done : !active||(a===task.state);
      }
      for(const field of box.querySelectorAll("[data-field]")) field.disabled=done;
    }
  }
  function event(task,state) { task.events.push({state,at_ms:task.origin===null ? 0 : Math.round(performance.now()-task.origin)}); task.state=state; }
  function act(task,action,box) {
    $("notice").textContent="";
    if(action==="start") {if(running!==null||task.state==="finished")return;task.origin=performance.now();task.events=[{state:"active",at_ms:0}];task.state="active";running=task.id;}
    else if(action==="skip") {if(running!==null||task.state==="finished")return;task.result="not_attempted";task.state="finished";task.help=box.querySelector('[data-field="help"]').value.trim();task.notes=box.querySelector('[data-field="notes"]').value;box.querySelector('[data-field="result"]').value="not_attempted";}
    else if(running===task.id) {
      if(action==="finish") {
        const result=box.querySelector('[data-field="result"]').value, help=box.querySelector('[data-field="help"]').value.trim(), notes=box.querySelector('[data-field="notes"]').value.trim();
        if(!["assisted","unassisted","incomplete"].includes(result)||(result==="assisted"&&!help)||(result==="unassisted"&&help)||(result==="incomplete"&&!notes)) {$("notice").textContent="결과를 선택하고 도움 여부·미완료 이유를 맞게 기록해 주세요.";return;}
        task.result=result;task.help=help;task.notes=notes;event(task,"finished");running=null;
      } else if(["active","waiting","paused"].includes(action) && action!==task.state) event(task,action);
    }
    refresh();
  }
  tasks.forEach((task,index)=>{
    const box=element("article",null,{class:"task","data-task":task.id});
    box.append(element("h2",`${task.id}. ${task.title}`),element("p",definitions[index][1]),element("div","미실시",{class:"status"}),element("div","",{class:"clock"}));
    const actions=element("div",null,{class:"actions"});
    for(const [action,label] of [["start","시작"],["waiting","대기"],["paused","중단"],["active","조작 재개"],["finish","종료"],["skip","미실시로 기록"]]) {
      const b=element("button",label,{"data-action":action});b.onclick=()=>act(task,action,box);actions.append(b);
    }
    box.append(actions); const fields=element("div",null,{class:"fields"});
    const label=element("label","과업 결과"), select=element("select",null,{"data-field":"result"});
    for(const [v,t] of [["","선택"],["unassisted","도움 없이 완료"],["assisted","도움 후 완료"],["incomplete","미완료"],["not_attempted","미실시"]]) {const option=element("option",t,{value:v});if(v==="not_attempted")option.disabled=true;select.append(option);}label.append(select);fields.append(label);
    const help=element("label","제공한 도움"), input=element("input",null,{"data-field":"help",maxlength:500});help.append(input);fields.append(help);box.append(fields);
    const notes=element("label","막힌 지점·참가자 의견·미완료 이유"), textarea=element("textarea",null,{"data-field":"notes",maxlength:3000});notes.append(textarea);box.append(notes);$("tasks").append(box);
  });
  $("export").onclick=()=>{
    const required=["participant","observer","date","version","mode","phase","scenario"];
    if(required.some(k=>!$(k).value.trim())||!$("consent").checked){$("notice").textContent="필수 검토 조건과 기록 동의를 입력해 주세요.";return;}
    if(running!==null||tasks.some(t=>t.state!=="finished")){ $("notice").textContent="진행 중인 과업을 끝내고 나머지는 미실시로 기록해 주세요.";return; }
    const record={schema:"harbinger-retest-v1",record_kind:$("kind").value,consent:true,exported_at:new Date().toISOString(),experience:$("experience").value,
      time_note:"Browser monotonic elapsed time; waiting and pauses manually marked by observer; not request latency or independent authenticity proof."};
    required.forEach(k=>record[k]=$(k).value.trim());
    record.tasks=tasks.map(t=>({id:t.id,title:t.title,result:t.result,help:t.help,notes:t.notes,events:t.events,...sum(t)}));
    const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:"application/json"})), a=element("a",null,{href:url,download:`harbinger-retest-${record.phase}-${record.date}.json`});
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    $("notice").textContent="JSON을 내려받았습니다. 공개 인용 전에는 참가자의 별도 동의를 확인하세요.";
  };
  window.addEventListener("beforeunload",e=>{if(tasks.some(t=>t.events.length)){e.preventDefault();e.returnValue="";}});
  setInterval(refresh,250);refresh();
})();
