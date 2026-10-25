/** Presentation preferences only. Never store account balances or trade decisions. */
export function readPreference(key:string):string|null {
  try{return localStorage.getItem(`parlay-ui-${key}`)}catch{return null}
}
export function savePreference(key:string,value:string){
  try{localStorage.setItem(`parlay-ui-${key}`,value)}catch{/* Private storage may be unavailable. */}
}
