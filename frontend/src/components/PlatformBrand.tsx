import { Tooltip } from 'antd'
import { siFacebook, siInstagram, siMeta, siTiktok, siYoutube, type SimpleIcon } from 'simple-icons'

export type SocialPlatform = 'youtube' | 'tiktok' | 'instagram' | 'facebook' | 'meta'

export const socialPlatformLabel:Record<SocialPlatform,string> = {
  youtube:'YouTube',
  tiktok:'TikTok',
  instagram:'Instagram',
  facebook:'Facebook',
  meta:'Meta',
}

const platformIcons:Record<SocialPlatform,SimpleIcon> = {
  youtube:siYoutube,
  tiktok:siTiktok,
  instagram:siInstagram,
  facebook:siFacebook,
  meta:siMeta,
}

export function normalizeSocialPlatform(platform:string):SocialPlatform|null {
  const value=platform.toLowerCase()
  return value in platformIcons ? value as SocialPlatform : null
}

export function PlatformLogo({platform,size=18,className='',tooltip=true}:{platform:string;size?:number;className?:string;tooltip?:boolean}){
  const key=normalizeSocialPlatform(platform)
  if(!key)return null
  const icon=platformIcons[key]
  const logo=<span className={`platform-logo ${className}`.trim()} style={{width:size,height:size}} role="img" aria-label={socialPlatformLabel[key]}>
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d={icon.path} fill={`#${icon.hex}`}/></svg>
  </span>
  return tooltip?<Tooltip title={socialPlatformLabel[key]}>{logo}</Tooltip>:logo
}

export function PlatformBadge({platform,size=18,showLabel=false}:{platform:string;size?:number;showLabel?:boolean}){
  const key=normalizeSocialPlatform(platform)
  if(!key)return <span className="platform-brand-name">{platform}</span>
  return <span className={`platform-brand-badge ${showLabel?'with-label':'logo-only'}`}>
    <PlatformLogo platform={key} size={size} tooltip={!showLabel}/>
    {showLabel&&<span>{socialPlatformLabel[key]}</span>}
  </span>
}

export function PlatformOption({platform,label}:{platform:string;label?:string}){
  const key=normalizeSocialPlatform(platform)
  return <span className="platform-option">
    {key&&<PlatformLogo platform={key} size={17} tooltip={false}/>}<span>{label||key&&socialPlatformLabel[key]||platform}</span>
  </span>
}

export function PlatformLogoGroup({platforms=['youtube','tiktok','instagram','facebook']}:{platforms?:SocialPlatform[]}){
  return <span className="platform-logo-group" aria-label="全部平台">
    {platforms.map(platform=><PlatformLogo key={platform} platform={platform} size={16} tooltip={false}/>) }
  </span>
}
