"use strict";
/** Credential is encrypted and maintained by native n8n, never exported to node outputs. */
class ProcureFlowApi {
  constructor() {
    this.name="procureFlowApi";
    this.displayName="ProcureFlow 업무 API";
    this.documentationUrl="https://github.com/lyonbegin/procureflow/blob/main/n8n/README.md";
    this.properties=[
      {displayName:"내부 FastAPI URL",name:"baseUrl",type:"string",default:"https://procureflow-api-production.up.railway.app",required:true},
      {displayName:"관리자 인증 토큰",name:"adminToken",type:"string",typeOptions:{password:true},default:"",required:true},
    ];
  }
}
module.exports={ProcureFlowApi};
