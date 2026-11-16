"""Render the small HPGL subset used by the pinned S-52 pattern/line catalogue.

Coordinates are 0.01 mm; 3.2 px/mm follows the supplied raster symbol scale.
Output is antialiased; no arbitrary PostScript or executable content is evaluated.
"""
import math
import re
from PIL import Image, ImageDraw


def render(element, colors, pattern=False, scale=.032):
    vector=element.find('vector')
    if vector is None: raise ValueError('No vector definition')
    hpgl=element.findtext('HPGL') or vector.findtext('HPGL') or ''
    origin=vector.find('origin')
    ox,oy=float(origin.get('x')),float(origin.get('y'))
    width,height=float(vector.get('width')),float(vector.get('height'))
    distance=vector.find('distance')
    gap=float(distance.get('min')) if pattern and distance is not None else 0
    pad=0 if pattern else 2
    w=max(1,math.ceil((width+gap)*scale)+2*pad)
    h=max(1,math.ceil((height+gap)*scale)+2*pad)
    if w>2048 or h>2048: raise ValueError('Vector tile too large')
    ss=4
    image=Image.new('RGBA',(w*ss,h*ss))
    draw=ImageDraw.Draw(image)
    refs=element.findtext('color-ref') or ''
    palette={refs[i]:colors[refs[i+1:i+6]] for i in range(0,len(refs),6)}
    colour=colors['CHBLK']; penwidth=1; position=(ox,oy); polygon=None
    def point(p): return ((p[0]-ox+gap/2)*scale*ss+pad*ss,(p[1]-oy+gap/2)*scale*ss+pad*ss)
    for op,args in re.findall(r'([A-Z]{2})([^;]*);?',hpgl):
        nums=[float(x) for x in args.split(',') if x] if op not in ('SP',) else []
        if op=='SP': colour=palette.get(args,colors['CHBLK'])
        elif op=='SW': penwidth=max(.6,nums[0]*.6)
        elif op in ('PU','PD'):
            points=list(zip(nums[::2],nums[1::2]))
            if op=='PD' and not points:
                cx,cy=point(position);r=max(1,penwidth*ss/2)
                draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=colour)
            if op=='PD' and points:
                draw.line([point(position)]+[point(p) for p in points],fill=colour,width=max(1,round(penwidth*ss)))
            if polygon is not None: polygon.extend(points)
            if points: position=points[-1]
        elif op=='CI':
            cx,cy=point(position); radius=nums[0]*scale*ss
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),outline=colour,width=max(1,round(penwidth*ss)))
        elif op=='PM':
            if nums[0]==0: polygon=[position]
        elif op=='FP':
            if polygon and len(polygon)>2: draw.polygon([point(p) for p in polygon],fill=colour)
        elif op=='EP':
            if polygon and len(polygon)>2: draw.line([point(p) for p in polygon+[polygon[0]]],fill=colour,width=max(1,round(penwidth*ss)))
        elif op=='ST': pass  # transparency is encoded in the RGBA background
        else: raise ValueError('Unsupported HPGL opcode '+op)
    return image.resize((w,h),Image.Resampling.LANCZOS)
