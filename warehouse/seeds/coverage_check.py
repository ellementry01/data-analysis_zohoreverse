"""Independent coverage check: every location / channel value found in the source files must be
mapped in the seed CSVs or listed as an open question. Exit code 1 if anything is missing."""
import csv, json, os, sys, pandas as pd
U = "/mnt/user-data/uploads"; S = os.path.dirname(os.path.abspath(__file__))
la = {(r['source_name'],r['source_field'],r['source_value']) for r in csv.DictReader(open(f"{S}/ref_location_alias.csv"))}
ca = {(r['source_name'],r['source_field'],r['source_value']) for r in csv.DictReader(open(f"{S}/ref_channel_alias.csv"))}
px = {r['doc_prefix'] for r in csv.DictReader(open(f"{S}/ref_document_prefix_location.csv"))}
unres = {(u[0],u[1],u[2]) for u in json.load(open(f"{S}/_mapping_model.json"))["UNRESOLVED"]}
def prefix(doc):
    out=[]
    for s in str(doc).split('/'):
        if s.isdigit(): break
        out.append(s)
    return '/'.join(out)
checks = []   # (what, source, field, values, mapping_set)
rs = pd.read_excel(f"{U}/Retail_Sales_01-04-2026_to_15-09-2026.xlsx","Sheet1")
ds = pd.read_excel(f"{U}/Domestic_Sales_01-04-2026_to_15-09-2026.xlsx","Sheet1")
rr = pd.concat([pd.read_excel(f"{U}/{f}","Sheet1") for f in ["Retail_Sales_Return_Current_FY.xlsx","Retail_Sales_Return_01-04-2025_to_31-03-2026.xlsx"]])
dr = pd.concat([pd.read_excel(f"{U}/{f}","Sheet1") for f in ["Domestic_Sale_Return_Current_FY.xlsx","Domestic_Sale_Return_01-04-2025_to_31-03-2026.xlsx"]])
so = pd.read_excel(f"{U}/Stock_Transfer_01-04-2026_to_15-09-2026.xlsx","Sheet1"); si = pd.read_excel(f"{U}/Stock_Transfer_Inward_01-04-2026_to_15-09-2026.xlsx","Sheet1")
inv = pd.read_excel(f"{U}/Inventory_report_15_Sept.xls","ChannelwiseStock",header=None); hdr = inv.iloc[18]
inv_locs = [hdr[j] for j in range(13,inv.shape[1]) if pd.notna(hdr[j]) and hdr[j] not in ('Active MRP','Total')]
inv_filter = [x.strip() for x in str(inv.iloc[10][2]).split(',') if x.strip()]   # report channel filter (row 11)
bi = pd.read_excel(f"{U}/Blinkit_inventory_sep_26.xlsx","Stock On Hand"); im = pd.read_excel(f"{U}/Instamart_inventory_26_sep_26.xlsx",sheet_name=0)
L = [("location","ERP_INVENTORY_SNAPSHOT","location column header",sorted(set(inv_locs)|set(inv_filter))),
     ("location","ERP_RETAIL_SALES","CHANNELNAME",rs['CHANNELNAME'].dropna().unique()),
     ("location","ERP_DOMESTIC_SALES","CHANNELNAME",ds['CHANNELNAME'].dropna().unique()),
     ("location","ERP_DOMESTIC_RETURN","CHANNELNAME",dr['CHANNELNAME'].dropna().unique()),
     ("location","ERP_RETAIL_RETURN","CONTACTNAME",rr['CONTACTNAME'].dropna().unique()),
     ("location","ERP_STOCK_TRANSFER_OUT","CONTACTNAME",so['CONTACTNAME'].dropna().unique()),
     ("location","ERP_STOCK_TRANSFER_IN","CONTACTNAME",si['CONTACTNAME'].dropna().unique()),
     ("location","BLINKIT_INVENTORY","Warehouse Facility Name",bi['Warehouse Facility Name'].dropna().unique()),
     ("location","INSTAMART_INVENTORY","FacilityName",im['FacilityName'].dropna().unique())]
C = [("channel","ERP_RETAIL_SALES","CONTACTNAME",rs['CONTACTNAME'].dropna().unique()),
     ("channel","ERP_RETAIL_RETURN","CONTACTNAME",rr['CONTACTNAME'].dropna().unique())]
total=missing=0; report=[]
for kind,src,field,vals in L+C:
    m = la if kind=="location" else ca
    for v in vals:
        v=str(v).strip(); total+=1
        if (src,field,v) in m: status="MAPPED"
        elif (src,field,v) in unres: status="OPEN QUESTION"
        else: status="MISSING"; missing+=1
        report.append((kind,src,field,v,status))
out_pfx = sorted(set(so['DOCNUM'].map(prefix)))
for p in out_pfx:
    total+=1
    st = "MAPPED" if p in px else ("OPEN QUESTION" if ("ERP_STOCK_TRANSFER_OUT","DOCNUM prefix",p) in unres else "MISSING")
    missing += st=="MISSING"; report.append(("transfer prefix","ERP_STOCK_TRANSFER_OUT","DOCNUM prefix",p,st))
df = pd.DataFrame(report, columns=["kind","source","field","value","status"])
print(df.groupby(["kind","status"]).size().unstack(fill_value=0).to_string())
print("\nNot mapped:"); print(df[df.status!="MAPPED"].to_string(index=False))
df.to_csv(f"{S}/_coverage_report.csv", index=False)
print(f"\n{total} distinct values checked; MISSING = {missing}")
sys.exit(1 if missing else 0)
