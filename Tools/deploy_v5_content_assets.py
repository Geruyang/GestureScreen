"""Create the original ROI illustration used by the built-in guide."""
from pathlib import Path
from PIL import Image, ImageDraw
root=Path(__file__).resolve().parents[1]
out=root/'Assets/content/roi.png'
im=Image.new('RGB',(160,72),(15,24,40)); d=ImageDraw.Draw(im)
d.rectangle((5,5,104,66),outline=(70,110,150),width=2)
d.rectangle((27,9,86,62),outline=(40,220,170),width=2)
d.text((111,12),'ROI',fill=(40,220,170))
d.line((111,31,91,31),fill=(40,220,170),width=2)
d.polygon(((91,31),(96,28),(96,34)),fill=(40,220,170))
d.text((111,45),'HOLD',fill=(230,235,245))
out.parent.mkdir(parents=True,exist_ok=True);im.save(out)
