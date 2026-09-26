"""Stage OTHER and annotation-excluded background crops for visual review."""
import argparse
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw
from import_external_dataset import hagrid_candidates, write_external_frame


def intersects(a,b):
    return a[0]<b[0]+b[2] and a[0]+a[2]>b[0] and a[1]<b[1]+b[3] and a[1]+a[3]>b[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--existing",type=Path,required=True)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    annotations=json.loads((a.root/"annotations.json").read_text(encoding="utf-8"))
    existing=json.loads(a.existing.read_text(encoding="utf-8"))
    used={row["provenance"]["source_item_id"] for row in existing}
    cal_users={row["provenance"]["subject_id"] for row in existing if row["split"]=="calibration"}
    rows=[]
    for source_class in ("no_gesture","like","dislike","ok","rock","call","four"):
        count=0
        for item in hagrid_candidates(a.root,annotations,source_class):
            item_id=f'hagrid-{item["item_id"]}-{source_class}'
            if item_id in used or item["user_id"] in cal_users:
                continue
            prov={"dataset":"HaGRID","source_page_url":"https://github.com/hukenovs/hagrid",
                  "source_item_id":item_id,"subject_id":item["user_id"],"source_label":source_class,
                  "license_id":"HaGRID custom attribution/share-alike-like license",
                  "license_url":"https://github.com/hukenovs/hagrid/blob/master/license/en_us.pdf",
                  "mapping_rule_id":"non-target-hand-pose-to-OTHER","manual_review_status":"pending"}
            row=write_external_frame(a.output,"OTHER","train",f'hagrid-user-{item["user_id"]}',
                                     item["path"].read_bytes(),item["bbox"],prov,len(rows))
            rows.append(row)
            count+=1
            if count==12:
                break
    for path in sorted((a.root/"point").glob("*.jpg")):
        item=annotations["point"].get(path.stem)
        if not item or item["user_id"] in cal_users:
            continue
        with Image.open(path) as original:
            original=original.convert("RGB")
            width,height=original.size
            cw=int(min(width*.38,height*.38*4/3))
            ch=int(cw*3/4)
            boxes=[(b[0]*width,b[1]*height,b[2]*width,b[3]*height) for b in item["bboxes"]]
            candidates=[(0,0,cw,ch),(width-cw,0,cw,ch),(0,height-ch,cw,ch),(width-cw,height-ch,cw,ch)]
            chosen=next((box for box in candidates if not any(intersects(box,hand) for hand in boxes)),None)
            if chosen is None:
                continue
            x,y,w,h=chosen
            background=original.crop((x,y,x+w,y+h))
            buffer=io.BytesIO()
            background.save(buffer,format="PNG")
        prov={"dataset":"HaGRID background-only derived crop","source_page_url":"https://github.com/hukenovs/hagrid",
              "source_item_id":f'hagrid-{path.stem}-background','subject_id':item["user_id"],
              "source_label":"point; selected crop excludes all annotated hand boxes",
              "original_jpeg_sha256":__import__('hashlib').sha256(path.read_bytes()).hexdigest(),
              "background_crop_source_pixels":[x,y,x+w,y+h],
              "license_id":"HaGRID custom attribution/share-alike-like license",
              "license_url":"https://github.com/hukenovs/hagrid/blob/master/license/en_us.pdf",
              "mapping_rule_id":"hand-box-excluded-background-requires-visual-review","manual_review_status":"pending"}
        rows.append(write_external_frame(a.output,"EMPTY","train",f'hagrid-user-{item["user_id"]}',
                                         buffer.getvalue(),(0,0,w,h),prov,len(rows)))
        if sum(row["label"]=="EMPTY" for row in rows)==80:
            break
    (a.output/"candidate_rows.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    for start in range(0,len(rows),48):
        sheet=Image.new("RGB",(8*160,6*144),"white")
        draw=ImageDraw.Draw(sheet)
        for index,row in enumerate(rows[start:start+48]):
            x,y=index%8*160,index//8*144
            with Image.open(a.output/row["preview_file"]) as im:
                sheet.paste(im.resize((160,120)),(x,y))
            draw.text((x,y+120),f'{start+index} {row["label"]}',fill="black")
        sheet.save(a.output/f'review-{start//48+1:02d}.jpg')
    print({label:sum(row["label"]==label for row in rows) for label in ("OTHER","EMPTY")})


if __name__=="__main__":
    main()
