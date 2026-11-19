import {datasets,plans,traces,sweeps} from '../api/business.js';
export const store={datasets:[],plans:[],traces:[],sweeps:[],user:null};
export async function refresh(){[store.datasets,store.plans,store.traces,store.sweeps]=await Promise.all([datasets.list(),plans.list(),traces.list(),sweeps.list()]);}
