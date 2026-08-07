export type CoverKind='vertical'|'square'|'horizontal'

export const coverImageSpecs:Record<CoverKind,{width:number;height:number;label:string}>={
 vertical:{width:1440,height:1920,label:'竖版 3:4'},
 square:{width:1200,height:1200,label:'方形 1:1'},
 horizontal:{width:1920,height:1080,label:'横版 16:9'},
}

export type PreparedCoverImage={
 file:File
 sourceWidth:number
 sourceHeight:number
 targetWidth:number
 targetHeight:number
 cropped:boolean
 resized:boolean
}

const loadImage=(file:File)=>new Promise<HTMLImageElement>((resolve,reject)=>{
 const url=URL.createObjectURL(file)
 const image=new window.Image()
 image.onload=()=>{URL.revokeObjectURL(url);resolve(image)}
 image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('无法读取这张图片，请改用 JPG、PNG 或 WebP 文件'))}
 image.src=url
})

const toJpeg=(canvas:HTMLCanvasElement)=>new Promise<Blob>((resolve,reject)=>{
 canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('图片转换失败，请更换图片后重试')),'image/jpeg',.92)
})

export async function prepareCoverImage(source:File,kind:CoverKind):Promise<PreparedCoverImage>{
 if(!source.type.startsWith('image/')&&!/\.(jpe?g|png|webp)$/i.test(source.name))throw new Error('请选择图片文件')
 const image=await loadImage(source)
 const sourceWidth=image.naturalWidth
 const sourceHeight=image.naturalHeight
 if(!sourceWidth||!sourceHeight)throw new Error('无法识别图片尺寸')

 const {width:targetWidth,height:targetHeight}=coverImageSpecs[kind]
 const targetRatio=targetWidth/targetHeight
 const sourceRatio=sourceWidth/sourceHeight
 let sourceX=0
 let sourceY=0
 let cropWidth=sourceWidth
 let cropHeight=sourceHeight
 if(sourceRatio>targetRatio){
  cropWidth=Math.round(sourceHeight*targetRatio)
  sourceX=Math.round((sourceWidth-cropWidth)/2)
 }else if(sourceRatio<targetRatio){
  cropHeight=Math.round(sourceWidth/targetRatio)
  sourceY=Math.round((sourceHeight-cropHeight)/2)
 }

 const canvas=document.createElement('canvas')
 canvas.width=targetWidth
 canvas.height=targetHeight
 const context=canvas.getContext('2d')
 if(!context)throw new Error('当前浏览器无法处理图片')
 context.imageSmoothingEnabled=true
 context.imageSmoothingQuality='high'
 context.fillStyle='#fff'
 context.fillRect(0,0,targetWidth,targetHeight)
 context.drawImage(image,sourceX,sourceY,cropWidth,cropHeight,0,0,targetWidth,targetHeight)

 const blob=await toJpeg(canvas)
 const stem=source.name.replace(/\.[^.]+$/,'')||'cover'
 const file=new File([blob],`${stem}_${kind}_${targetWidth}x${targetHeight}.jpg`,{type:'image/jpeg',lastModified:Date.now()})
 return{
  file,sourceWidth,sourceHeight,targetWidth,targetHeight,
  cropped:cropWidth!==sourceWidth||cropHeight!==sourceHeight,
  resized:cropWidth!==targetWidth||cropHeight!==targetHeight,
 }
}
