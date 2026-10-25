"use strict";
/** Native n8n node. All requests use the credential encrypted in n8n.
 * There is NO generic webhook, arbitrary remote URL, or bid submission.
 * 15 PF workflows plan from actual official evidence, dispatch one bounded
 * existing G2B worker job, then independently read worker+evidence states.
 */
const featureOptions=require("./features.json");
const allowedHost=/^https:\/\/(?:procureflow-api-production\.up\.railway\.app|[a-z0-9-]+\.procureflow\.internal)$/i;
const PF_IDS=Array.from({length:15},(_,i)=>"PF"+String(i+1).padStart(2,"0"));
const operations=[
  {name:"공식 증빙 조회 (읽기)",value:"inspect"},
  {name:"증빙 검사 (작업 등록 안 함)",value:"check"},
  {name:"기존 단일 업무 Job 직접 등록 (관리자)",value:"collect"},
  {name:"다음 실제 수집 작업 계획",value:"planNext"},
  {name:"검증된 계획으로 단일 Worker Job 실행",value:"dispatchPlanned"},
  {name:"실제 Worker 결과·증빙 검증 상태",value:"jobStatus"},
];
class ProcureFlow {
  constructor() {
    this.description={
      displayName:"ProcureFlow · 조달청 104기능",
      name:"procureFlow",
      icon:"fa:briefcase",
      group:["transform"],version:1,
      subtitle:"={{$parameter[\"operation\"]}}",
      description:"공식 증빙 기반 계획·안전한 Worker Job 실행·실제 상태 대조. 입찰 제출 금지.",
      defaults:{name:"ProcureFlow 업무"},
      inputs:["main"],outputs:["main"],
      credentials:[{name:"procureFlowApi",required:true}],
      properties:[
        {displayName:"작업",name:"operation",type:"options",options:operations,default:"inspect"},
        {displayName:"업무 기능",name:"featureNo",type:"options",options:featureOptions,default:1,
         displayOptions:{show:{operation:["inspect","check","collect"]}}},
        {displayName:"PF 업무 플로우",name:"flowId",type:"options",
          options:PF_IDS.map(v=>({name:v,value:v})),default:"PF01",
          displayOptions:{show:{operation:["planNext","dispatchPlanned","jobStatus"]}}},
        {displayName:"공고번호",name:"bidNo",type:"string",default:"R26BK01787028",required:true},
        {displayName:"업무별 인수 JSON",name:"parameters",type:"json",default:"{}",
         description:"공고번호·세부종목·기관은 실제 공식 원본만 허용합니다.",
         displayOptions:{show:{operation:["check","collect"]}}},
      ],
    };
  }
  async execute() {
    const items=this.getInputData();
    const credentials=await this.getCredentials("procureFlowApi");
    const base=String(credentials.baseUrl||"").replace(/\/+$/,"");
    if(!allowedHost.test(base))throw new Error("ProcureFlow credentials must use the approved procurement API host");
    const token=String(credentials.adminToken||"");
    if(!token)throw new Error("ProcureFlow admin credential is required");
    const out=[];
    for(let index=0;index<items.length;index++) {
      const operation=this.getNodeParameter("operation",index);
      const bidNo=String(this.getNodeParameter("bidNo",index)).trim();
      if(!/^R[0-9]{2}BK[0-9]{8}$/.test(bidNo))throw new Error("Invalid official G2B bid number");
      const req={headers:{"Authorization":"Bearer "+token},json:true,timeout:35000};
      let featureNo=null,flowId=null;
      let jobRequested=false;
      if(["inspect","check","collect"].includes(operation)) {
        featureNo=Number(this.getNodeParameter("featureNo",index));
        if(!Number.isInteger(featureNo)||featureNo<1||featureNo>104)
          throw new Error("Invalid official G2B function");
        const uri=base+"/api/g2b/cases/"+encodeURIComponent(bidNo)+"/features/"+featureNo;
        req.url=operation==="inspect"?uri:uri+"/run";
        req.method=operation==="inspect"?"GET":"POST";
        if(operation!=="inspect") {
          let params;
          try {params=JSON.parse(String(this.getNodeParameter("parameters",index)||"{}"));}
          catch{throw new Error("업무별 인수 JSON이 올바르지 않습니다");}
          if(!params||Array.isArray(params)||typeof params!=="object")
            throw new Error("인수는 JSON 객체여야 합니다");
          for(const field of ["bid_no","bid_ord","detail10","agency","agency_code"])
            if(Object.prototype.hasOwnProperty.call(params,field))
              throw new Error("원본 공고·분류 정보는 외부 입력으로 변경할 수 없습니다");
          req.body={mode:operation,parameters:params};
        }
        jobRequested=operation==="collect";
      } else {
        flowId=this.getNodeParameter("flowId",index);
        if(!PF_IDS.includes(flowId))throw new Error("Unknown native PF flow");
        const api=base+"/api/n8n/operational/flows/"+flowId;
        if(operation==="planNext") {
          req.url=api+"/next-action?bid_no="+encodeURIComponent(bidNo);
          req.method="GET";
        } else if(operation==="dispatchPlanned") {
          const plan=items[index].json;
          if(!plan||plan.status!=="ACTIONABLE"||!plan.candidate||!plan.request_key)
            throw new Error("Official dispatch plan is not ACTIONABLE");
          if(plan.flow_id!==flowId||plan.bid_no!==bidNo)
            throw new Error("Dispatch plan official case or PF flow mismatch");
          featureNo=Number(plan.candidate.feature_no);
          if(!Number.isInteger(featureNo)||featureNo<1||featureNo>104)
            throw new Error("Plan feature number is outside the registry");
          req.method="POST";req.url=api+"/dispatch";
          req.body={bid_no:bidNo,feature_no:featureNo,request_key:plan.request_key,parameters:{}};
          jobRequested=true;
        } else if(operation==="jobStatus") {
          const input=items[index].json||{};
          const jobId=Number(input.job_id??input.response?.job_id);
          if(!Number.isSafeInteger(jobId)||jobId<=0)
            throw new Error("Worker job_id required to inspect real execution");
          req.method="GET";
          req.url=api+"/jobs/"+jobId+"?bid_no="+encodeURIComponent(bidNo);
        } else {
          throw new Error("Unsupported ProcureFlow n8n operation");
        }
      }
      const response=await this.helpers.httpRequest(req);
      if(response===null||typeof response!=="object")
        throw new Error("ProcureFlow API returned no structured evidence");
      out.push({json:{
        ...items[index].json,
        flow_id:flowId??items[index].json?.flow_id??null,
        feature_no:featureNo??items[index].json?.feature_no??null,
        operation,official_bid_no:bidNo,
        response, ...(operation==="jobStatus"?response:{}),
        ...(operation==="dispatchPlanned"?{job_id:response.job_id}:{}),
        job_requested:jobRequested,
        acceptance_independent_of_worker:true,
        bid_submitted:false,
      },pairedItem:{item:index}});
    }
    return [out];
  }
}
module.exports={ProcureFlow};
