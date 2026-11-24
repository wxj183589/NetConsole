import { describe, expect, it } from 'vitest'
import { hierarchyGroups, nodeFields, uniqueDevices } from './infrastructurePresentation'
import type { Infrastructure, InfrastructureDevice, InfrastructureNode } from '../../../api/railInfrastructure'
import type { Section } from '../../../types/railTransitBaseData'

const station = (uid: string, code: string, name: string): InfrastructureNode => ({ uid,code,name,kind:'station',source:'engineering',station:null,aliases:[],projects:[],devices:[],sections:[],ac_service_stations:[] })
const device: InfrastructureDevice = {device_uuid:'switch-stable',name:'Switch',device_role:'switch',device_type:'SW',role:'接入交换机',source:'engineering',section_uid:null}
const start=station('first','0101','正式站'), end=station('second','0102','终点站')
const section = {id:'section-stable',name:'旧区间展示名',start_node_uid:'first',end_node_uid:'second',start_station:'旧起点名',end_station:'旧终点名',ap_count:3,line_direction:'上行',line_side:'右线'} as Section
const between: InfrastructureNode = {...station('section-stable','','旧区间展示名'),kind:'section',sections:[section],devices:[device]}
const snapshot: Infrastructure={site_id:'demo',site_name:'Test',line_name:'Line',schema_available:true,unassociated_device_count:0,unresolved_binding_count:0,nodes:[start,end,between],unassociated_devices:[],device_count:1}

describe('infrastructure hierarchy presentation',()=>{
  it('omits sections from the organization without mutating facts',()=>{
    const before=JSON.stringify(snapshot)
    const groups=hierarchyGroups(snapshot,'')
    expect(groups.map(group=>group.name)).toEqual(['控制中心','正线车站','车辆段与停车场','车载设备'])
    expect(groups[1].items.map(item=>item.uid)).toEqual(['first','second'])
    expect(groups.flatMap(group => group.items)).not.toContain(between)
    expect(JSON.stringify(snapshot)).toBe(before)
  })
  it('finds stations by code while excluding section-only matches',()=>{
    expect(hierarchyGroups(snapshot,'Switch')[1].items).toEqual([])
    expect(hierarchyGroups(snapshot,'0102')[1].items).toEqual([end])
  })
  it('keeps multiple projects and active distinct engineering names while hiding null/blank fields',()=>{
    const node={...start,devices:[device,device],projects:[{project_id:'p1',stage:'一期',name:'初建'},{project_id:'p2',stage:'二期',name:'扩建'}],aliases:[
      {name:'工程名',name_type:'engineering',valid_to:null},{name:'正式站',name_type:'engineering',valid_to:null},{name:'过去工程名',name_type:'engineering',valid_to:'2020-01-01'},
    ]} as InfrastructureNode
    const fields=nodeFields(node)
    expect(fields).toContainEqual({label:'建设项目',value:'一期 初建、二期 扩建'})
    expect(fields).toContainEqual({label:'工程名称',value:'工程名'})
    expect(fields).toContainEqual({label:'下属交换机',value:'1'})
    expect(fields.some(field=>field.value.includes('过去工程名'))).toBe(false)
    expect(uniqueDevices(node.devices)).toHaveLength(1)
    expect(nodeFields({...start,code:'',projects:[]})).toEqual([{label:'下属交换机',value:'0'}])
  })
  it('does not guess CT/CW assignments from device names or an absent legacy train link',()=>{
    const train={...station('train','01','列车01'),kind:'train',devices:[{...device,device_uuid:'ct',name:'当前MR',role:'MR-CT'},{...device,device_uuid:'decoy',name:'MR-CW',role:''}]} as InfrastructureNode
    expect(nodeFields(train)).toEqual([{label:'列车编号',value:'01'},{label:'MR-CT',value:'当前MR'},{label:'MR-CW',value:'未配置'},{label:'当前关系',value:'已关联'}])
    expect(nodeFields({...train,devices:[]})).toContainEqual({label:'当前关系',value:'未配置'})
  })
})
