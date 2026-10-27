import { createApp, h, ref, computed, onMounted, nextTick } from 'vue';
import { VueFlow, Handle, Position, useVueFlow } from '@vue-flow/core';
import { Background } from '@vue-flow/background';
import { Controls } from '@vue-flow/controls';
import '@vue-flow/core/dist/style.css';
import '@vue-flow/core/dist/theme-default.css';
import '@vue-flow/controls/dist/style.css';
import './style.css';

const EDITOR = 'https://procureflow-n8n-github-source-test-production.up.railway.app';
const API = 'https://procureflow-api-production.up.railway.app';
const CAT = {
  manualTrigger: { symbol: '▶', caption: '수동 실행', tone: 'trigger' },
  webhook: { symbol: '⌁', caption: 'Webhook', tone: 'trigger' },
  scheduleTrigger: { symbol: '◷', caption: '정기 실행', tone: 'trigger' },
  code: { symbol: '{ }', caption: 'Code', tone: 'code' },
  httpRequest: { symbol: '◎', caption: 'HTTP Request', tone: 'request' },
  if: { symbol: '◇', caption: 'IF', tone: 'decision' },
  wait: { symbol: '◷', caption: 'Wait', tone: 'wait' },
  set: { symbol: '≡', caption: 'Edit Fields', tone: 'code' }
};

function linksOf(workflow) {
  const ids = new Map((workflow.nodes || []).map(n=>[n.name,n.id || n.name]));
  const edges = [];
  for (const [source,outputs] of Object.entries(workflow.connections || {})) {
    for (const [kind,groups] of Object.entries(outputs)) {
      for (let outputIndex=0; outputIndex<groups.length; outputIndex++) {
        for (const target of groups[outputIndex] || []) {
          if (!ids.has(source) || !ids.has(target.node)) continue;
          edges.push({id: 'edge-'+edges.length,source:ids.get(source),target:ids.get(target.node),
            type:'smoothstep',sourceHandle:null,targetHandle:null,animated:false,
            style:{stroke:'#a9b8c5',strokeWidth:1.8}});
        }
      }
    }
  }
  return edges;
}
function asGraph(w) {
  return {nodes:(w.nodes || []).map(n=>({id:n.id || n.name,type:'procure',
      position:{x:Number(n.position?.[0] || 0),y:Number(n.position?.[1] || 0)},
      data:{label:n.name,raw:n}})),
    edges:linksOf(w)};
}
const NodeCard = {
  props:['id','data','selected'],
  setup(props) {
    return ()=> {
      const raw = props.data.raw || {};
      const kind = (raw.type || '').split('.').pop();
      const cfg = CAT[kind] || {symbol:'▣',caption:kind,tone:'code'};
      return h('div',{class:['node-card',cfg.tone,props.selected?'selected':''].join(' ')},[
        h(Handle,{type:'target',position:Position.Left,class:'conn-handle'}),
        h('div',{class:'node-symbol'},cfg.symbol),
        h('div',{class:'node-label'},props.data.label),
        h('div',{class:'node-kind'},cfg.caption),
        h(Handle,{type:'source',position:Position.Right,class:'conn-handle'})
      ]);
    };
  }
};
const FlowPane = {
  props:['graph','onPick'],
  setup(props) {
    return ()=>h(VueFlow,{nodes:props.graph.nodes,edges:props.graph.edges,
      nodesDraggable:false,nodesConnectable:false,elementsSelectable:true,
      fitViewOnInit:true,fitViewOnInitOptions:{padding:0.23},minZoom:0.15,maxZoom:2,
      onNodeClick:({node})=>props.onPick(node)},{
        'node-procure':p=>h(NodeCard,p),
        default:()=>[h(Background,{patternColor:'#e7ebee',gap:20,size:1}),
                     h(Controls,{showInteractive:false})]
      });
  }
};
const App = {
  setup() {
    const catalog = ref([]);
    const group = ref('operational');
    const id = ref('PF05');
    const workflow = ref(null);
    const selected = ref(null);
    const loadError = ref('');
    const loading = ref(true);
    const graph = computed(()=>workflow.value ? asGraph(workflow.value):{nodes:[],edges:[]});
    const nativeLink = computed(()=>workflow.value?.id ? EDITOR+'/workflow/'+encodeURIComponent(workflow.value.id) : EDITOR);
    function chooseFromHash() {
      const match = /^#\/(operational|scenarios)\/(PF\d{2}|S\d{2})$/.exec(location.hash);
      if (match) {group.value=match[1];id.value=match[2];}
    }
    async function choose(g,i) {
      group.value=g;id.value=i;selected.value=null;loadError.value='';loading.value=true;
      const hash='#/'+g+'/'+i; if (location.hash!==hash) history.replaceState(null,'',hash);
      try {
        const r=await fetch('/api/workflows/'+g+'/'+i,{cache:'no-store'});
        if (!r.ok) throw new Error('HTTP '+r.status);
        const body=await r.json();workflow.value=body.workflow;
      } catch (e) {workflow.value=null;loadError.value='워크플로 JSON을 불러오지 못했습니다: '+e.message;}
      finally {loading.value=false;}
    }
    onMounted(async ()=>{
      try {
        const r=await fetch('/api/catalog',{cache:'no-store'});
        if (!r.ok) throw new Error('Catalog HTTP '+r.status);
        const body=await r.json();catalog.value=body.workflows;
        chooseFromHash();await choose(group.value,id.value);
      } catch(e) {loading.value=false;loadError.value=e.message;}
    });
    const button=(g,item)=>h('button',{class:['flow-option',group.value===g&&id.value===item.id?'active':''].join(' '),
      onClick:()=>choose(g,item.id),title:item.name},
      [h('span',{class:'flow-code'},item.id),h('span',{class:'flow-title'},item.name.replace(/^\[(?:운영|테스트) [^\]]+\]\s*/,'').slice(0,30)),h('small',String(item.nodeCount))]);
    return ()=>h('div',{class:'layout'},[
      h('header',{class:'topbar'},[
        h('div',{class:'app-title'},[h('strong','n8n 실제 노드 · 조달청 자동화'),h('small','n8n 워크플로 원본 JSON 25개 · Vue Flow 1.48.0 · 로그인 없는 조회 전용')]),
        h('div',{class:'links'},[
          h('a',{href:API,target:'_blank',rel:'noopener'},'조달청 자동화 메인'),
          h('a',{href:nativeLink.value,target:'_blank',rel:'noopener'},'실제 n8n 편집기에서 열기')])
      ]),
      h('div',{class:'workspace'},[
        h('nav',{class:'sidebar'},[
          h('div',{class:'nav-caption'},'운영 플로우 (15)'),
          ...catalog.value.filter(x=>x.group==='operational').map(item=>button('operational',item)),
          h('div',{class:'nav-caption second'},'테스트 시나리오 (10)'),
          ...catalog.value.filter(x=>x.group==='scenarios').map(item=>button('scenarios',item))
        ]),
        h('main',{class:'canvas-wrap'},[
          h('div',{class:'canvas-heading'},[
            h('strong',workflow.value?.name || '실제 노드 플로우'),
            h('span',workflow.value?('n8n 원본 노드 '+workflow.value.nodes.length+'개 · 실제 연결 '+graph.value.edges.length+'개'):'')
          ]),
          h('div',{class:'canvas'},[
            loading.value?h('p',{class:'loading'},'실제 워크플로 JSON을 불러오는 중입니다'):null,
            loadError.value?h('p',{class:'error'},loadError.value):null,
            workflow.value?h(FlowPane,{key:id.value,graph:graph.value,onPick:n=>selected.value=n}):null
          ]),
          h('div',{class:'notice'},'이 화면은 n8n에 등록한 실제 워크플로 JSON의 조회 전용 시각화입니다. 실행·수정은 실제 n8n 편집기에서만 수행됩니다.')
        ]),
        selected.value?h('aside',{class:'inspect'},[
          h('div',{class:'inspect-head'},[
            h('strong','실제 n8n 노드 정보'),
            h('button',{onClick:()=>selected.value=null,ariaLabel:'닫기'},'×')
          ]),
          h('h3',selected.value.data.raw.name),
          h('p','유형: '+selected.value.data.raw.type),
          h('h4','실제 노드 parameters'),
          h('pre',JSON.stringify(selected.value.data.raw.parameters || {},null,2)),
          h('h4','노드 식별자'),
          h('code',selected.value.id)
        ]):null
      ])
    ]);
  }
};
createApp(App).mount('#app');
