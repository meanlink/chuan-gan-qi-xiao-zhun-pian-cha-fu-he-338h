/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:'waiting'|'running'|'completed'|'failed'|'withdrawn',result:Object,approved:boolean,run_id:number|null,shared:number,recoveries:number,withdrawn:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
export {};
