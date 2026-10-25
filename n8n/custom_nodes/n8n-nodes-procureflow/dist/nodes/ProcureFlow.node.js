"use strict";
const options=require("./features.json");
const ALLOWED_HOST_PATTERN=/^https:\/\/[a-z0-9._-]+(?::443)?$/i;
class ProcureFlow {
  constructor() {
    this.description={
      displayName:"ProcureFlow · 조달청 104기능",
      name:"procureFlow",
      icon:"fa:briefcase",
      group:["transform"],
      version:1,
      subtitle:"={{$parameter[\"featureNo\"]}} · {{$parameter[\"operation\"]}}",
      description:"검증된 공식 증빙 조회 또는 명시적 실행 요청. 자동 투찰 없음.",
      defaults:{name:"ProcureFlow 업무"},
      inputs:["main"],outputs:["main"],
      credentials:[{name:"procureFlowApi",required:true}],
      properties:[
        {displayName:"업무 기능",name:"featureNo",type:"options",options,default:1,required:true},
        {displayName:"작업",name:"operation",type:"options",options:[
          {name:"공식 증빙·상태 조회 (읽기)",value:"inspect"},
          {name:"증빙 검사 (작업 등록 안 함)",value:"check"},
          {name:"실제 안전 업무 Job 등록 (관리자 권한)",value:"collect"},
        ],default:"inspect"},
        {displayName:"공고번호",name:"bidNo",type:"string",default:"R26BK01787028",required:true},
        {displayName:"업무별 인수 JSON",name:"parameters",type:"json",default:"{}",description:"예: 10년 이력 candidate_limit=2. 공고번호·분류는 덮어쓸 수 없습니다.",
          displayOptions:{show:{operation:["check","collect"]}}},
      ],
    };
  }
  async execute() {
    const items=this.getInputData();
    const credentials=await this.getCredentials("procureFlowApi");
    const base=String(credentials.baseUrl||"").replace(/\/+$/,"");
    if(!ALLOWED_HOST_PATTERN.test(base))throw new Error("ProcureFlow API must be a trusted HTTPS service URL");
    const output=[];
    for(let index=0;index<items.length;index++){
      const featureNo=Number(this.getNodeParameter("featureNo",index));
      const operation=this.getNodeParameter("operation",index);
      const bidNo=String(this.getNodeParameter("bidNo",index)).trim();
      if(!Number.isInteger(featureNo)||featureNo<1||featureNo>104)throw new Error("Invalid official G2B function");
      if(!/^R[0-9]{2}BK[0-9]{8}$/.test(bidNo))throw new Error("Invalid G2B bid identifier");
      if(!["inspect","check","collect"].includes(operation))throw new Error("Invalid G2B operation");
      const endpoint=base+"/api/g2b/cases/"+encodeURIComponent(bidNo)+"/features/"+featureNo;
      const req={url: operation==="inspect"?endpoint:endpoint+"/run",
        method:operation==="inspect"?"GET":"POST",
        headers:{"Authorization":"Bearer "+String(credentials.adminToken||"")},
        json:true,timeout:30000};
      if(operation!=="inspect"){
        let params={};
        try {params=JSON.parse(String(this.getNodeParameter("parameters",index)||"{}"));}
        catch {throw new Error("업무별 인수 JSON이 올바르지 않습니다");}
        if(!params||Array.isArray(params)||typeof params!=="object")throw new Error("인수는 JSON 객체여야 합니다");
        for(const forbidden of ["bid_no","bid_ord","detail10","agency","agency_code"])
          if(Object.prototype.hasOwnProperty.call(params,forbidden))throw new Error("원본 공고·분류 정보는 외부 입력으로 변경할 수 없습니다");
        req.body={mode:operation,parameters:params};
      }
      const response=await this.helpers.httpRequest(req);
      output.push({json:{feature_no:featureNo,operation,official_bid_no:bidNo,
        response,job_requested:operation==="collect",
        business_completion_not_implied:true,bid_submitted:false},
        pairedItem:{item:index}});
    }
    return [output];
  }
}
module.exports={ProcureFlow};
