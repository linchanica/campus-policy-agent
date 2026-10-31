/** WeChat returns logical CSS pixels; do not multiply capsule coordinates by pixelRatio. */
export type WindowMetrics={windowWidth?:number;windowHeight?:number;statusBarHeight?:number}
export type CapsuleMetrics={left?:number;top?:number;height?:number}

export function nativeNavigation(windowInfo:WindowMetrics={},capsule:CapsuleMetrics={}){
 const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)
 const width=finite(windowInfo.windowWidth)&&windowInfo.windowWidth>0?windowInfo.windowWidth:375
 const status=finite(windowInfo.statusBarHeight)&&windowInfo.statusBarHeight>=0?windowInfo.statusBarHeight:20
 const validCapsule=finite(capsule.left)&&capsule.left>0&&capsule.left<width&&finite(capsule.top)&&capsule.top>=status&&finite(capsule.height)&&capsule.height>0
 const rightInset=validCapsule?width-capsule.left!+8:104
 const navigationHeight=validCapsule?Math.max(44,capsule.height!+2*(capsule.top!-status)):44
 const headerHeight=status+navigationHeight
 const shellStyle:Record<string,string>={}
 if(finite(windowInfo.windowHeight)&&windowInfo.windowHeight>0)shellStyle.height=windowInfo.windowHeight+'px'
 return {headerHeight,rightInset,validCapsule,
  headerStyle:{height:headerHeight+'px',paddingTop:status+'px',paddingRight:rightInset+'px'},
  shellStyle,overlayStyle:{top:headerHeight+'px'}}
}
