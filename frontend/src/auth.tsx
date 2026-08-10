import { createContext,useContext } from 'react'
import type { AuthUser } from './api'

export type AuthState={user:AuthUser;logout:()=>Promise<void>}
export const AuthContext=createContext<AuthState|null>(null)
export const useAuth=()=>{
 const value=useContext(AuthContext)
 if(!value)throw new Error('AuthContext 尚未初始化')
 return value
}
