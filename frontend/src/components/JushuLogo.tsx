export function JushuLogo({size=40}:{size?:number}){
 return <svg
  aria-label="剧枢"
  className="jushu-logo"
  width={size}
  height={size}
  viewBox="0 0 40 40"
  fill="none"
  xmlns="http://www.w3.org/2000/svg"
 >
  <rect width="40" height="40" rx="12" fill="#CFF595"/>
  <rect x="7" y="8" width="23" height="17" rx="5" fill="#B1FFEC" stroke="#11150F" strokeWidth="2.4"/>
  <rect x="11" y="15" width="23" height="17" rx="5" fill="#FFF588" stroke="#11150F" strokeWidth="2.4"/>
  <path d="m20 20 7 3.5-7 3.5v-7Z" fill="#11150F"/>
  <circle cx="11" cy="12" r="1.5" fill="#11150F"/>
  <circle cx="29" cy="28" r="1.5" fill="#11150F"/>
 </svg>
}
