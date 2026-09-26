"""Merge reviewed candidates into a separate, strictly audited 800-frame dataset."""
import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw
from dataset import LABELS, preprocess, read_dataset
from import_external_dataset import copy_personal, hagrid_candidates, write_external_frame

# Conservative exclusions recorded after viewing the numbered contact sheets.
HAGRID_REJECT={34,40,50,63,90,124,162,170,177,191,198,211,237,256,258,266,267,280,296,300,316,330}
POINT_REJECT={7,8,9,11,12,13,17,18,19,20,21,27,28,29,32,33,38,39,40,41,46,50,55,56,57,58,59,60,61,62,63,64,67,71,72,73,74}


def dhash(raw):
    tensor,_=preprocess(raw,"msb_first",640)
    values=bytes((value+128)&255 for value in tensor)
    image=Image.frombytes("L",(96,96),values).resize((9,8))
    pixels=list(image.getdata())
    return sum(int(pixels[y*9+x]>pixels[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--personal",type=Path,required=True)
    p.add_argument("--cache",type=Path,required=True)
    p.add_argument("--hagrid",type=Path,required=True)
    p.add_argument("--points",type=Path,required=True)
    p.add_argument("--extras",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        raise ValueError("refusing to overwrite a non-empty dataset")
    a.output.mkdir(parents=True,exist_ok=True)
    personal,personal_rejected=copy_personal(a.output,a.personal.resolve())
    annotations=json.loads((a.cache/"hagrid-100"/"annotations.json").read_text(encoding="utf-8"))
    candidates=[]
    excluded=[]
    for source_root,reject_set in ((a.hagrid,HAGRID_REJECT),(a.points,POINT_REJECT),(a.extras,set())):
        source_rows=json.loads((source_root/"candidate_rows.json").read_text(encoding="utf-8"))
        for number,source_row in enumerate(source_rows):
            if number in reject_set:
                excluded.append({"source":str(source_root),"index":number,"reason":"visual screening: pose, blur or uncertain visibility"})
                continue
            row=dict(source_row)
            provenance=dict(row["provenance"])
            if source_root==a.points:
                source_bytes=(source_root/"source_frames"/(row["record_id"]+".png")).read_bytes()
                bbox=tuple(provenance["source_bbox_xywh"])
                session=row["session"]
                # The first two recording identities and hand-only identity
                # form one conservative calibration cohort (no train leakage).
                participant=provenance["subject_id"]
                split="calibration" if participant in ("p0","p00","p01","p02") else "train"
                row=write_external_frame(a.output,row["label"],split,session,source_bytes,bbox,provenance,len(candidates))
            elif source_root==a.extras and row["label"]=="OTHER":
                source_class=provenance["source_label"]
                source_id=provenance["source_item_id"].split("hagrid-",1)[1].rsplit("-"+source_class,1)[0]
                item=next(item for item in hagrid_candidates(a.cache/"hagrid-100",annotations,source_class) if item["item_id"]==source_id)
                row=write_external_frame(a.output,"OTHER","train",row["session"],item["path"].read_bytes(),item["bbox"],provenance,len(candidates))
            else:
                for field in ("file","preview_file"):
                    target=a.output/row[field]
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source_root/row[field],target)
            row["label_provenance"]="source_annotation_and_assistant_visual_contact_sheet_screening"
            row["provenance"]["manual_review_status"]="assistant_screened_not_independent_expert_ground_truth"
            row["provenance"]["review_source"]={"candidate_directory":str(source_root),"contact_sheet_index":number}
            if "HaGRID" in row["provenance"]["dataset"]:
                row["provenance"]["license_url"]="https://github.com/hukenovs/hagrid/blob/master/license/en_us.pdf"
                row["provenance"]["license_file"]="licenses/hagrid-en.pdf"
                row["provenance"]["attribution"]="Kapitanov et al., HaGRID; convenience mirror GestureDetectionConnoisseurs"
                row["provenance"]["adaptation_license"]="same HaGRID Public license with attribution and conditions reserved"
            candidates.append(row)
    positive=[row for row in candidates if row["label"]!="EMPTY"]
    negative=[row for row in candidates if row["label"]=="EMPTY"]
    raw_hashes={row["sha256"] for row in personal}
    input_hashes=set()
    for row in personal:
        tensor,_=preprocess((a.output/row["file"]).read_bytes(),row["byte_order"],640)
        input_hashes.add(hashlib.sha256(tensor).hexdigest())
    selected=[]
    for row in positive+negative:
        raw=(a.output/row["file"]).read_bytes()
        tensor,quality=preprocess(raw,"msb_first",640)
        input_hash=hashlib.sha256(tensor).hexdigest()
        if not quality["acceptable"] or row["sha256"] in raw_hashes or input_hash in input_hashes:
            excluded.append({"file":row["file"],"reason":"quality gate or exact raw/input duplicate"})
            continue
        if len(selected)==503:
            break
        raw_hashes.add(row["sha256"])
        input_hashes.add(input_hash)
        selected.append(row)
    if len(selected)!=503:
        raise ValueError(f"only {len(selected)} valid external frames; do not pad with duplicates")
    samples=personal+selected
    manifest={"schema_version":1,"preprocessing":"rgb565-roi192-gray96-v1","samples":samples,
              "note":"800 derived frames, not 800 independent people/recordings. Original personal manifest unchanged.",
              "provenance_summary":{"personal_declared":308,"personal_included":len(personal),
                                    "personal_quality_excluded":personal_rejected,"external_included":len(selected),
                                    "personal_manifest_sha256":hashlib.sha256(a.personal.read_bytes()).hexdigest(),
                                    "external_exclusions":excluded},"validated_for_business":False}
    manifest_path=a.output/"dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report,_=read_dataset(manifest_path,complete=True)
    if report["debug_quality_rejected"] or report["sample_count"]!=800:
        raise ValueError("final audit failed")
    report["all_exact_input_duplicates"]=0
    report["class_counts"]=dict(Counter(row["label"] for row in samples))
    report["source_counts"]=dict(Counter(row.get("source","unknown") for row in samples))
    report["business_accuracy_verified"]=False
    (a.output/"dataset_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    hashes=[dhash((a.output/row["file"]).read_bytes()) for row in samples]
    pairs=[]
    for i in range(len(samples)):
        for j in range(i):
            distance=(hashes[i]^hashes[j]).bit_count()
            if distance<=3:
                pairs.append({"first":j,"second":i,"dhash_distance":distance,
                              "cross_split":samples[i]["split"]!=samples[j]["split"],
                              "same_session":samples[i]["session"]==samples[j]["session"]})
    (a.output/"near_duplicate_candidates.json").write_text(json.dumps(pairs,indent=2),encoding="utf-8")
    licenses=a.output/"licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copy2(a.cache/"hagrid-license-en.pdf",licenses/"hagrid-en.pdf")
    (a.output/"README.md").write_text(
        "# 800-frame gesture dataset\n\n297 valid personal + 503 external RGB565_BE frames. Original 308 personal records are not changed; 11 near-black EMPTY frames are excluded only in this derivative.\n\n"
        "Sources: https://github.com/hukenovs/hagrid (custom Public license with attribution and conditions reserved, copied in licenses/hagrid-en.pdf); https://data.mendeley.com/datasets/n66hhk695h/2 (CC BY 4.0, Rahat, Parvin, Nur). HaGRID images mirrored by GestureDetectionConnoisseurs/hagrid_subsets. Changes: hand-centered 4:3 crop with recorded black boundary padding, resize to 320x240, fixed RGB565_BE quantization; EMPTY frames are reviewed background crops excluding annotated hands.\n\n"
        "Personal sessions are kept intact: left-hand session train, newest session validation, original right-hand session test, separate EMPTY session calibration. RGB-NHG identities p0/p01/p02 are calibration-only; remaining identities train. HaGRID splits are by user_id. The 800 frames are NOT 800 independent recordings. Counts are not balanced; see dataset_audit.json.\n\n"
        "No training or board flashing was performed. Contact-sheet screening is not independent expert annotation or an accuracy guarantee. dHash candidates are in near_duplicate_candidates.json; near-duplicate audit must be reviewed before interpreting holdout metrics as leakage-free. Keep HaGRID attribution and its adaptation license with redistribution; do not relabel all sources as CC0.\n",
        encoding="utf-8")
    for start in range(0,len(selected),48):
        sheet=Image.new("RGB",(8*160,6*144),"white")
        draw=ImageDraw.Draw(sheet)
        for index,row in enumerate(selected[start:start+48]):
            x,y=index%8*160,index//8*144
            with Image.open(a.output/row["preview_file"]) as im:
                sheet.paste(im.resize((160,120)),(x,y))
            draw.rectangle((x+32,y+12,x+128,y+108),outline="cyan")
            draw.text((x,y+120),f'{start+index}: {row["label"]}',fill="black")
        sheet.save(a.output/f'external-review-{start//48+1:02d}.jpg')
    print(json.dumps({"count":800,"classes":report["class_counts"],"splits":report["counts"],
                      "near_candidates":len(pairs),"cross_split_near_candidates":sum(pair["cross_split"] for pair in pairs)},indent=2))


if __name__=="__main__":
    main()
