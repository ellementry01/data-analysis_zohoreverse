"""Builds ref seed CSVs + a review workbook from ONE definition, so they cannot drift.
Every row carries the evidence it is based on. is_confirmed=True only where the business said so."""
import csv, os
OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- LOCATIONS
# (code, erp_name, name, type, operated_by, gst, city, stock_holding, sellable, system_of_record, active, confirmed, units_15sep, evidence, question)
L = []
def loc(*a): L.append(a)
loc("BAGRU_WH","08 Jaipur Branch","Bagru Warehouse (Head Office)","CENTRAL_WAREHOUSE","SELF","08","Bagru",True,True,"ERP",True,True,82509,
    "Business confirmed: 08 Jaipur Branch = Bagru warehouse; HO is in Bagru. Bare 'Dileep Essentials Pvt Ltd' uses JPR document prefixes.","")
loc("POPUP_BAGRU","08 Bagru Popup","Bagru Popup Store","POPUP_STORE","SELF","08","Bagru",True,True,"ERP",True,False,368,"Name; holds stock","Is this the same place as 'Dileep Essentials Pvt Ltd Bagru' (transfer prefix BAG/)?")
loc("STORE_JPR_CSCHEME","08 Jaipur - C-Scheme","Jaipur C-Scheme Store","OWN_STORE","SELF","08","Jaipur",True,True,"ERP",True,False,2488,"Retail invoices with cash / swipe payments; long name 'Dileep Essentials Pvt Ltd C-Scheme'","")
loc("STORE_HYD_BANJARA","36 HYD - Banjara Hills","Hyderabad Banjara Hills Store","OWN_STORE","SELF","36","Hyderabad",True,True,"ERP",True,False,2855,"Retail invoices with cash / swipe payments; long name 'Dileep Essentials Pvt Ltd HYD Store'","")
loc("STORE_JPR_MEERAKI","08 Jaipur - Meeraki","Jaipur Meeraki","OWN_STORE","SELF","08","Jaipur",True,True,"ERP",True,False,145,"Holds stock but has NO retail invoices Apr-Sep 2026","Own store, SIS or franchise? Is it the 'Jaipur Store' seen in FY25-26 returns?")
for code,erp,name,city,gst in [("STORE_DEL_GK","07 Delhi - GK Store","Delhi GK Store","Delhi","07"),
    ("STORE_BLR_INDIRANAGAR","29 Bengaluru - Indiranagar","Bengaluru Indiranagar","Bengaluru","29"),
    ("STORE_BLR_VRMALL","29 Bengaluru - VR Mall","Bengaluru VR Mall","Bengaluru","29"),
    ("STORE_MUM_INFINITI","27 Mumbai - Infiniti Malad","Mumbai Infiniti Malad","Mumbai","27"),
    ("STORE_MUM_SIB_BANDRA","27 Mumbai - SIB Bandra","Mumbai SIB Bandra","Mumbai","27"),
    ("STORE_GOA_ANJUNA","30 Goa - Anjuna","Goa Anjuna","Anjuna","30"),
    ("STORE_AMD_CGROAD","24 CG Road - Ahmd","Ahmedabad CG Road","Ahmedabad","24")]:
    loc(code,erp,name,"OWN_STORE","SELF",gst,city,True,True,"ERP",False,False,0,"Zero stock on 15-Sep and no retail invoices Apr-Sep 2026","Closed? And was it own, SIS or franchise?")
for code,erp,name,city,gst in [("DEPL_DELHI","07 DEPL Delhi","DEPL Delhi","Delhi","07"),("DEPL_LUCKNOW","09 DEPL - Lucknow","DEPL Lucknow","Lucknow","09"),
    ("DEPL_MUMBAI_PPOB","27 DEPL Mumbai - PPOB","DEPL Mumbai PPOB","Mumbai","27")]:
    loc(code,erp,name,"OTHER","SELF",gst,city,True,False,"ERP",False,False,0,"Zero stock on 15-Sep; purpose not known","What is this location (office, old warehouse, GST registration)?")
loc("DFAL","08 Essential - DFAL","Essential - DFAL","OTHER","SELF","08",None,True,False,"ERP",True,False,688,"688 units of 15 SKUs; transfer prefixes IS/DF and RC/DF","What is DFAL, and is its stock sellable?")
# In the stock report's channel filter but with NO column in the 15-Sep report (see issue log)
loc("HEAD_OFFICE","Head Office","Head Office (Bagru)","HEAD_OFFICE","SELF","08","Bagru",False,False,"NONE",True,False,None,
    "Selected in the stock report filter; no stock column. Business: HO is in Bagru","Does Head Office ever hold stock?")
loc("REPAIR_DAMAGE","08 Repair and Damage","Repair and Damage","REPAIR_DAMAGE","SELF","08",None,True,False,"ERP",False,False,None,
    "Selected in the stock report filter; no stock column","Does this hold damaged stock? Why has it no column in the report?")
loc("OFFLINE_WH","08 Offline - WH","Offline Warehouse","OFFLINE_WAREHOUSE","SELF","08",None,True,False,"ERP",False,False,None,
    "Selected in the stock report filter; no stock column","What is the Offline warehouse, and is it still used?")
loc("STORE_JPR_MANSAROVAR","08 Jaipur - Mansarovar","Jaipur Mansarovar","OWN_STORE","SELF","08","Jaipur",True,True,"ERP",False,False,None,
    "Selected in the stock report filter; no stock column","Closed store? Own, SIS or franchise?")
for code,erp,city,gst in [("FBA_DED1","07 FBA WH - DED1","Delhi","07"),("FBA_ISK3","27 FBA WH - ISK3","Nashik","27"),
                          ("FBA_BLX9","29 FBA WH - BLX9 (Consolidate)","Bengaluru","29")]:
    loc(code,erp,"Amazon FBA "+erp.split(" - ")[-1],"AMAZON_FBA","AMAZON",gst,city,True,True,"ERP",False,False,None,
        "Selected in the stock report filter; no stock column","Still in use?")
# Amazon FBA
fba = [("FBA_JAIPUR","08 FBA WH - Jaipur","Jaipur","08",15,"Long name 'Dileep Essentials Pvt Ltd FBA'; prefix FBA/STK"),
 ("FBA_THANE","27 FBA WH - Thane","Thane","27",496,"Long name 'Dileep Essentials Pvt Ltd Thane FBA'; prefix THA/IC; returns BOM7"),
 ("FBA_BLR5","29 FBA WH - Bangalore 5","Bengaluru","29",0,"Zero stock"),
 ("FBA_BLR7","29 FBA WH - Bangalore 7","Bengaluru","29",376,"Long name 'Dileep Essentials Pvt Ltd Bengaluru 7 FBA'; prefix FBL7/STK; 2 SKUs negative"),
 ("FBA_NAG1","27 FBA WH - NAG1","Nagpur","27",0,"Zero stock"),
 ("FBA_HYD","36 FBA WH - Hyderabad","Hyderabad","36",306,"Long name 'Dileep Essentials Pvt Ltd Hyderabad FBA'; prefix FBAHYD/STK"),
 ("FBA_DEX3","07 FBA WH - Delhi X3","Delhi","07",177,"Long name 'Dileep Essentials Pvt Ltd Delhi FBA DEX3'; prefix FBAX3/STK"),
 ("FBA_PNQ2","07 FBA WH - Delhi Q2","Delhi","07",28,"Long name 'Dileep Essentials Pvt Ltd Delhi FBA PNQ2'; prefix FBAQ2/STK"),
 ("FBA_DEX8","07 FBA WH - Delhi X8","Delhi","07",42,"Long name 'Dileep Essentials Pvt Ltd Delhi FBA DEX8'; prefix FBAX8/STK"),
 ("FBA_BOM5","27 FBA WH - BOM5","Mumbai","27",98,"Long name 'Dileep Essentials Pvt Ltd BOM5 FBA'; prefix BOM/STK"),
 ("FBA_AMD2","24 FBA WH - AMD2","Ahmedabad","24",140,"Long name 'Dileep Essentials Pvt Ltd Ahmedabad FBA AMD2'; prefix AMD/DC"),
 ("FBA_LKO1","09 FBA WH - LKO1","Lucknow","09",110,"Long name 'Dileep Essentials Pvt Ltd Lucknow FBA LKO1'; prefix LK/DC"),
 ("FBA_DED5","06 FBA WH - DED5","Haryana","06",0,"Zero stock"),
 ("FBA_DED3","06 FBA WH - DED3","Haryana","06",4,"4 units"),
 ("FBA_DED4","06 FBA WH - DED4","Haryana","06",559,"Long name 'Dileep Essentials Pvt Ltd FBA DED4'; prefix ISU/D4"),
 ("FBA_CCX1","19 FBA WH - CCX1","Kolkata","19",251,"Long name 'Dileep Essentials Private Limited CCX1 FBA'; prefix ISU/CCX"),
 ("FBA_CCX2","19 FBA WH - CCX2","Kolkata","19",154,"Long name 'Dileep Essentials Pvt Ltd FBA CCX2'; prefix ISU/CX2"),
 ("FBA_CJB1","33 FBA WH - CJB1","Coimbatore","33",129,"Long name 'Dileep Essentials Private Limited CJB1 FBA'; prefix ISU/CJB"),
 ("FBA_MAA4","33 FBA WH - MAA4","Chennai","33",56,"Long name 'Dileep Essentials Private Limited MAA4 FBA'; prefix ISU/MAA")]
for code,erp,city,gst,units,ev in fba:
    loc(code,erp,"Amazon FBA "+erp.split(" - ")[-1],"AMAZON_FBA","AMAZON",gst,city,True,True,"ERP",units>0,False,units,
        ev+". Business confirmed FBA = Amazon warehouses holding our stock.","Inactive because zero stock - correct?" if units==0 else "")
# Blinkit
loc("BLINKIT_PUNE_P2","27 Blinkit - Pune P2","Blinkit Pune P2 Feeder","QC_FEEDER_WAREHOUSE","BLINKIT","27","Pune",True,True,"BLINKIT",True,False,267,
    "ERP location; Blinkit report 'Pune P2 - Feeder'; transfer prefix P2/STK","Which is the truth for this stock: ERP or Blinkit's report? (proposed: Blinkit)")
loc("BLINKIT_MUM_M10","27 Blinkit - Mumbai M10","Blinkit Mumbai M10 Feeder","QC_FEEDER_WAREHOUSE","BLINKIT","27","Mumbai",True,True,"BLINKIT",True,False,53,
    "ERP location; Blinkit report 'Mumbai M10 - Feeder'; transfer prefix M10/STK","Same question as Pune P2")
loc("BLINKIT_FARUKHNAGAR_SR",None,"Blinkit Farukhnagar SR","QC_FEEDER_WAREHOUSE","BLINKIT","06","Farukhnagar",True,True,"BLINKIT",True,False,None,
    "Only in Blinkit inventory report (not an ERP location)","")
# Instamart facilities
im = [("HYD IM2","HYDERABAD"),("MUM IM3","MUMBAI"),("DLHY GGNFC5","GURGAON"),("CHN ECOM","CHENNAI"),("CHE AMB IM2","CHENNAI"),("KOL IM2","KOLKATA"),
 ("BLR IM1","BANGALORE"),("AHM DELHIVERY","AHMEDABAD"),("MUM FC22","MUMBAI"),("HYD IM5","HYDERABAD"),("GOA IM1","CENTRAL GOA"),("VIZ IM1","VIZAG"),
 ("HYD IM1","HYDERABAD"),("DLHY GGNFC9","DELHI"),("BLR IM4","BANGALORE"),("CHD IM2","CHANDIGARH"),("PUN DELHIVERY","PUNE"),("NOI IM1","NOIDA"),
 ("GAU IM1","GUWAHATI"),("CBE IM1 TEMP","COIMBATORE"),("JAI IM1","JAIPUR"),("KOC IM1","KOCHI"),("BLR DHL","BANGALORE_2"),("BLR ECOM2","BANGALORE"),
 ("PUNE IM2 TEMP","PUNE"),("KOLKATA ECOM","KOLKATA"),("MUM IM1","MUMBAI"),("BLR IM3","BANGALORE"),("HYD IM4","HYDERABAD")]
city_state = {"HYDERABAD":"36","MUMBAI":"27","GURGAON":"06","CHENNAI":"33","KOLKATA":"19","BANGALORE":"29","BANGALORE_2":"29","AHMEDABAD":"24",
 "CENTRAL GOA":"30","VIZAG":"37","DELHI":"07","CHANDIGARH":"04","PUNE":"27","NOIDA":"09","GUWAHATI":"18","COIMBATORE":"33","JAIPUR":"08","KOCHI":"32"}
for fac,city in im:
    code = "IM_" + fac.replace(" ","_").upper()
    loc(code,None,"Instamart "+fac,"QC_PLATFORM_FACILITY","INSTAMART",city_state[city],city.title().replace("_2"," 2"),True,True,"INSTAMART",True,False,None,
        "Instamart inventory FacilityName (not an ERP location)","")

# Virtual locations required by the target design
loc("EMPLOYEE_EXHIBITION",None,"With employees (exhibitions)","EMPLOYEE_HOLDING","SELF","08",None,True,False,"NONE",True,False,None,
    "Virtual location: stock issued to employees for exhibitions until it comes back (BR-029)","")
loc("CONSIGN_BLINKIT",None,"Blinkit (Kiranakart) consignment stock","PARTNER_CONSIGNMENT","BLINKIT",None,None,True,True,"NONE",True,False,None,
    "Virtual location: stock invoiced to Kiranakart sale-or-return, until sold through or returned (BR-022). Separate from the Blinkit feeder locations the ERP tracks by stock transfer","Are Kiranakart invoices and transfers to Blinkit feeders two different supply routes?")

# ---------------------------------------------------------------- LOCATION ALIASES
LA = []  # (source, field, value, code, confirmed, evidence)
erp_names = {r[1]:r[0] for r in L if r[1]}
inv_headers = [r[1] for r in L if r[1]]
for n in inv_headers: LA.append(("ERP_INVENTORY_SNAPSHOT","location column header",n,erp_names[n],n=="08 Jaipur Branch","Exact ERP location name"))
for n in ['06 FBA WH - DED4','07 FBA WH - Delhi Q2','07 FBA WH - Delhi X3','08 FBA WH - Jaipur','08 Jaipur - C-Scheme','08 Jaipur Branch','09 FBA WH - LKO1',
          '19 FBA WH - CCX1','19 FBA WH - CCX2','24 FBA WH - AMD2','27 FBA WH - BOM5','27 FBA WH - Thane','29 FBA WH - Bangalore 7','33 FBA WH - CJB1',
          '33 FBA WH - MAA4','36 FBA WH - Hyderabad','36 HYD - Banjara Hills']:
    LA.append(("ERP_RETAIL_SALES","CHANNELNAME",n,erp_names[n],n=="08 Jaipur Branch","Exact ERP location name"))
for n in ['08 Jaipur - C-Scheme','08 Jaipur Branch','36 HYD - Banjara Hills']:
    LA.append(("ERP_DOMESTIC_SALES","CHANNELNAME",n,erp_names[n],n=="08 Jaipur Branch","Exact ERP location name"))
for n in ['08 Jaipur - C-Scheme','08 Jaipur Branch','27 Blinkit - Pune P2','36 HYD - Banjara Hills']:
    LA.append(("ERP_DOMESTIC_RETURN","CHANNELNAME",n,erp_names[n],n=="08 Jaipur Branch","Exact ERP location name"))
longmap = {
 'Dileep Essentials Private Limited CCX1 FBA':'FBA_CCX1','Dileep Essentials Private Limited CJB1 FBA':'FBA_CJB1','Dileep Essentials Private Limited MAA4 FBA':'FBA_MAA4',
 'Dileep Essentials Pvt Ltd':'BAGRU_WH','Dileep Essentials Pvt Ltd - DFAL':'DFAL','Dileep Essentials Pvt Ltd Ahmedabad FBA AMD2':'FBA_AMD2',
 'Dileep Essentials Pvt Ltd BOM5 FBA':'FBA_BOM5','Dileep Essentials Pvt Ltd Bengaluru 7 FBA':'FBA_BLR7','Dileep Essentials Pvt Ltd Blinkit Mumbai':'BLINKIT_MUM_M10',
 'Dileep Essentials Pvt Ltd Blinkit Pune':'BLINKIT_PUNE_P2','Dileep Essentials Pvt Ltd C-Scheme':'STORE_JPR_CSCHEME','Dileep Essentials Pvt Ltd Delhi FBA DEX3':'FBA_DEX3',
 'Dileep Essentials Pvt Ltd Delhi FBA DEX8':'FBA_DEX8','Dileep Essentials Pvt Ltd Delhi FBA PNQ2':'FBA_PNQ2','Dileep Essentials Pvt Ltd FBA':'FBA_JAIPUR',
 'Dileep Essentials Pvt Ltd FBA CCX2':'FBA_CCX2','Dileep Essentials Pvt Ltd FBA DED4':'FBA_DED4','Dileep Essentials Pvt Ltd HYD Store':'STORE_HYD_BANJARA',
 'Dileep Essentials Pvt Ltd Hyderabad FBA':'FBA_HYD','Dileep Essentials Pvt Ltd Lucknow FBA LKO1':'FBA_LKO1','Dileep Essentials Pvt Ltd Thane FBA':'FBA_THANE'}
long_ev = "Retail Sales bills this contact at that ERP location, and/or its transfer document prefix points to it"
st_out = ['Dileep Essentials Private Limited CCX1 FBA','Dileep Essentials Private Limited CJB1 FBA','Dileep Essentials Private Limited MAA4 FBA','Dileep Essentials Pvt Ltd',
 'Dileep Essentials Pvt Ltd - DFAL','Dileep Essentials Pvt Ltd Ahmedabad FBA AMD2','Dileep Essentials Pvt Ltd BOM5 FBA','Dileep Essentials Pvt Ltd Bagru',
 'Dileep Essentials Pvt Ltd Bengaluru 7 FBA','Dileep Essentials Pvt Ltd C-Scheme','Dileep Essentials Pvt Ltd Delhi FBA DEX3','Dileep Essentials Pvt Ltd FBA CCX2',
 'Dileep Essentials Pvt Ltd FBA DED4','Dileep Essentials Pvt Ltd HYD Store','Dileep Essentials Pvt Ltd Hyderabad FBA','Dileep Essentials Pvt Ltd Lucknow FBA LKO1',
 'Dileep Essentials Pvt Ltd Thane FBA']
st_in = st_out + ['Dileep Essentials Pvt Ltd Blinkit Mumbai','Dileep Essentials Pvt Ltd Blinkit Pune','Dileep Essentials Pvt Ltd Delhi FBA DEX8',
 'Dileep Essentials Pvt Ltd Delhi FBA PNQ2','Dileep Essentials Pvt Ltd FBA']
UNRESOLVED = []  # (source, field, value, where seen, question)
for src,vals in [("ERP_STOCK_TRANSFER_OUT",st_out),("ERP_STOCK_TRANSFER_IN",st_in)]:
    for v in vals:
        if v in longmap: LA.append((src,"CONTACTNAME",v,longmap[v],False,long_ev))
        else: UNRESOLVED.append((src,"CONTACTNAME",v,"Stock transfers (prefix BAG/DC, BAG/...)","Which location is 'Dileep Essentials Pvt Ltd Bagru'? It is NOT the bare 'Dileep Essentials Pvt Ltd' (= Bagru warehouse, prefix JPR). Is it '08 Bagru Popup'?"))
# FY25-26 transfer names (full exports, Oct 2026): the Amazon FBA code is part of the name; each code exists in the location master.
fy2526_fba = {'Dileep Essentials Private Limited DED5 FBA':'FBA_DED5','Dileep Essentials Pvt Ltd Bengaluru 5 FBA':'FBA_BLR5',
              'Dileep Essentials Pvt Ltd Delhi FBA DED1':'FBA_DED1','Dileep Essentials Pvt Ltd FBA DED3':'FBA_DED3'}
for src in ("ERP_STOCK_TRANSFER_OUT","ERP_STOCK_TRANSFER_IN"):
    have = {v for (s_,f_,v,*_) in LA if s_ == src and f_ == "CONTACTNAME"}
    for v,c in list(fy2526_fba.items()) + [(k,longmap[k]) for k in ('Dileep Essentials Pvt Ltd Delhi FBA DEX8','Dileep Essentials Pvt Ltd Delhi FBA PNQ2','Dileep Essentials Pvt Ltd FBA')]:
        if v not in have:
            LA.append((src,"CONTACTNAME",v,c,False,"FY25-26 transfers: the FBA code in the name is a location in the master (same naming as mapped FBA contacts)"))
for v,q in [("Dileep Essentials Pvt Ltd CG Road Ahmedabad","A store at CG Road, Ahmedabad in FY25-26 (1,534 transfer lines). Not in the Sep 2026 stock report: closed store? Add it as a location?"),
            ("Dileep Essentials Pvt Ltd Lucknow","Lucknow store (FY25-26 transfers and retail sales) or the Lucknow FBA (LKO1)?"),
            ("Dileep Essentials Pvt Ltd Jaipur Store","Which Jaipur store (FY25-26 transfers and sales)? Meeraki? C-Scheme?"),
            ("Dileep Essentials Pvt Ltd Mumbai PPOB","Mumbai PPOB (principal place of business) in FY25-26 transfers: a warehouse, a store or an office?"),
            ("Dileep Essentials Pvt Ltd Delhi","Delhi location in FY25-26 transfers: 07 DEPL Delhi, the GK store, or another?")]:
    UNRESOLVED.append(("ERP_STOCK_TRANSFER_OUT / IN","CONTACTNAME",v,"FY25-26 stock transfers",q))
# retail return receiving location
d2c = ['Shopify_Customer','Amazon Website','Amazon Seller Flex','Myntra Customer','Nykaa','Nykaa Fashion','Pepperfry Customer','Tata Cliq','Tata Cliq Mall',
       'Tata Cliq Mall - Furniture','FNP E Retail Marketplace','Flipkart Website','Ellementry International']
for v in d2c: LA.append(("ERP_RETAIL_RETURN","CONTACTNAME",v,"BAGRU_WH",False,"Return numbers for these contacts all use the JPR prefix (Bagru warehouse)"))
for v,c in longmap.items():
    if c.startswith("FBA_") or c.startswith("STORE_") or c=="BAGRU_WH" or c.startswith("BLINKIT"):
        LA.append(("ERP_RETAIL_RETURN","CONTACTNAME",v,c,False,"Return received back at this location (business confirmed for FBA)"))
UNRESOLVED.append(("ERP_RETAIL_RETURN","CONTACTNAME","Dileep Essentials Pvt Ltd Jaipur Store","FY25-26 retail returns, 7 returns, prefix JPR2","Which location is 'Jaipur Store'? (Meeraki? C-Scheme?)"))
UNRESOLVED.append(("ERP_RETAIL_RETURN","CONTACTNAME","Dileep Essentials Pvt Ltd Lucknow","FY25-26 retail returns","Is this '09 DEPL - Lucknow' or the Lucknow FBA (LKO1)?"))
for f,c in [("Pune P2 - Feeder","BLINKIT_PUNE_P2"),("Mumbai M10 - Feeder","BLINKIT_MUM_M10"),("Farukhnagar - SR","BLINKIT_FARUKHNAGAR_SR")]:
    LA.append(("BLINKIT_INVENTORY","Warehouse Facility Name",f,c,False,"Blinkit facility name; matches ERP Blinkit location code where one exists"))
for fac,city in im: LA.append(("INSTAMART_INVENTORY","FacilityName",fac,"IM_"+fac.replace(" ","_").upper(),False,"Instamart facility"))
LA.append(("WMS_DISPATCH","Order Serving Location","Warehouse","BAGRU_WH",True,"Business confirmed: all B2C dispatch is from Bagru"))

# ---------------------------------------------------------------- TRANSFER PREFIXES (sending location of outward documents)
PFX = [("AMD/DC","FBA_AMD2",24),("BOM/STK","FBA_BOM5",19),("FBA/STK","FBA_JAIPUR",4),("FBAHYD/STK","FBA_HYD",32),("FBAQ2/STK","FBA_PNQ2",9),
 ("FBAX3/STK","FBA_DEX3",7),("FBAX8/STK","FBA_DEX8",3),("FBL7/STK","FBA_BLR7",63),("HYD8/DC","STORE_HYD_BANJARA",5),("IS/DF","DFAL",6),
 ("ISU/CCX","FBA_CCX1",23),("ISU/CJB","FBA_CJB1",16),("ISU/CX2","FBA_CCX2",3),("ISU/D4","FBA_DED4",91),("ISU/MAA","FBA_MAA4",10),
 ("JPR/DC","BAGRU_WH",160),("JPR3/DC","STORE_JPR_CSCHEME",52),("LK/DC","FBA_LKO1",11),("M10/STK","BLINKIT_MUM_M10",7),("P2/STK","BLINKIT_PUNE_P2",2),
 ("THA/IC","FBA_THANE",64),
       ("ISU/DED5","FBA_DED5",129),("ISS/D3","FBA_DED3",19)  # FY25-26 exports, Oct 2026
       ,("AHM4/DC","STORE_AMD_CGROAD",41),("LUC9/DC","DEPL_LUCKNOW",47),("JPR2/DC","STORE_JPR_MEERAKI",54),("BAG/DC","POPUP_BAGRU",12),
       ("DEL/DC","DEPL_DELHI",4),("MUM/DC","DEPL_MUMBAI_PPOB",8)
]
UNRESOLVED.append(("ERP_STOCK_TRANSFER_OUT","DOCNUM prefix","BAG/DC","2 documents, sender = 'Dileep Essentials Pvt Ltd Bagru'","Resolved together with the 'Dileep Essentials Pvt Ltd Bagru' question above"))

# ---------------------------------------------------------------- CHANNELS
C = [  # code, name, sub, group, confirmed, note
 ("WEBSITE","Own Website","Shopify","D2C_WEBSITE",True,"Incl. COD (Delhivery, Shiprocket) and Snapmint - business confirmed via CONTACTNAME"),
 ("AMAZON_FBA","Amazon","FBA","MARKETPLACE",True,"Orders fulfilled from Amazon FBA warehouses"),
 ("AMAZON_SELF_SHIP","Amazon","Self-ship / Easyship","MARKETPLACE",False,"Contact 'Amazon Website', billed and shipped from Bagru; WMS shows Amazon_SC_Easyship"),
 ("AMAZON_SELLER_FLEX","Amazon","Seller Flex","MARKETPLACE",False,"Contact 'Amazon Seller Flex'"),
 ("MYNTRA","Myntra","Myntra","MARKETPLACE",False,""),
 ("NYKAA_FASHION","Nykaa","Nykaa Fashion","MARKETPLACE",False,""),
 ("NYKAA","Nykaa","Nykaa","MARKETPLACE",False,"Separate contact 'Nykaa' (34 lines) - kept as its own sub-channel"),
 ("TATA_CLIQ","Tata Cliq","Tata Cliq","MARKETPLACE",False,""),
 ("TATA_CLIQ_MALL","Tata Cliq","Tata Cliq Mall","MARKETPLACE",False,""),
 ("TATA_CLIQ_MALL_FURNITURE","Tata Cliq","Tata Cliq Mall - Furniture","MARKETPLACE",False,""),
 ("PEPPERFRY","Pepperfry","Pepperfry","MARKETPLACE",False,""),
 ("FNP","FNP","FNP E-Retail","MARKETPLACE",False,""),
 ("FLIPKART","Flipkart","Flipkart","MARKETPLACE",False,"Seen only in FY25-26 returns; no sales Apr-Sep 2026"),
 ("OWN_STORE","Own Stores","Own Stores","OFFLINE_RETAIL",False,"Store identity is the location, not the channel"),
 ("B2B","B2B / Wholesale","Outright","B2B",True,"Final invoices (business confirmed)"),
 ("FRANCHISE","Franchise Stores","Sale-or-return","B2B",True,"Business confirmed sale-or-return"),
 ("SIS","Shop-in-Shop","Sale-or-return","B2B",True,"Business confirmed sale-or-return"),
 ("BLINKIT","Blinkit","Quick commerce","QUICK_COMMERCE",True,"Sale-or-return"),
 ("INSTAMART","Instamart","Quick commerce","QUICK_COMMERCE",True,"Sale-or-return"),
 ("EXPORT_VIA_DILEEP","Exports","Via Dileep (cost-to-cost)","B2B",True,"Business confirmed"),
 ("EXPORT_DIRECT","Exports","Direct","B2B",False,"Only 2 Rs 1 lines (Hindustan Exports, Singapore)"),
 ("EXPORT_B2C","Exports","B2C export (Ellementry International)","D2C_WEBSITE",True,
  "Business confirmed (Oct 2026): Ellementry International = B2C export to consumers abroad; B2B exports go through Dileep (EXPORT_VIA_DILEEP)"),
 ("INTERNAL_EMPLOYEE","Internal","Employee exhibition stock","INTERNAL",True,"Not a sale; excluded from revenue"),
]
CA = []  # (source, field, value, channel, priority, confirmed, evidence)
fba_contacts = [k for k,v in longmap.items() if v.startswith("FBA_")]
retail_map = {'Shopify_Customer':('WEBSITE',True),'Amazon Website':('AMAZON_SELF_SHIP',False),'Amazon Seller Flex':('AMAZON_SELLER_FLEX',False),
 'Myntra Customer':('MYNTRA',False),'Nykaa':('NYKAA',False),'Nykaa Fashion':('NYKAA_FASHION',False),'Pepperfry Customer':('PEPPERFRY',False),
 'Tata Cliq':('TATA_CLIQ',False),'Tata Cliq Mall':('TATA_CLIQ_MALL',False),'Tata Cliq Mall - Furniture':('TATA_CLIQ_MALL_FURNITURE',False),
 'FNP E Retail Marketplace':('FNP',False),'Dileep Essentials Pvt Ltd C-Scheme':('OWN_STORE',False),'Dileep Essentials Pvt Ltd HYD Store':('OWN_STORE',False),
 'Dileep Essentials Pvt Ltd':('EXPORT_VIA_DILEEP',True),'Ellementry International':('EXPORT_B2C',True)}
for v in fba_contacts: retail_map[v] = ('AMAZON_FBA',True)
for src in ["ERP_RETAIL_SALES","ERP_RETAIL_RETURN"]:
    for v,(c,conf) in retail_map.items():
        CA.append((src,"CONTACTNAME",v,c,10,conf,"Retail CONTACTNAME = channel (business confirmed rule)"))
CA.append(("ERP_RETAIL_RETURN","CONTACTNAME","Flipkart Website","FLIPKART",10,False,"FY25-26 returns only"))
# FY25-26 retail SALES carry the same contacts the FY25-26 returns already map (same unconfirmed mapping, same evidence)
for v,c in [("Flipkart Website","FLIPKART"),("Dileep Essentials Pvt Ltd Blinkit Mumbai","BLINKIT"),("Dileep Essentials Pvt Ltd Blinkit Pune","BLINKIT"),
            ("Dileep Essentials Pvt Ltd Jaipur Store","OWN_STORE"),("Dileep Essentials Pvt Ltd Lucknow","OWN_STORE")]:
    CA.append(("ERP_RETAIL_SALES","CONTACTNAME",v,c,10,False,"FY25-26 sales; same contact as the mapped FY25-26 returns"))
CA.append(("ERP_RETAIL_RETURN","CONTACTNAME","Dileep Essentials Pvt Ltd Blinkit Mumbai","BLINKIT",10,False,"FY25-26 retail returns from a Blinkit location"))
CA.append(("ERP_RETAIL_RETURN","CONTACTNAME","Dileep Essentials Pvt Ltd Blinkit Pune","BLINKIT",10,False,"FY25-26 retail returns from a Blinkit location"))
CA.append(("ERP_RETAIL_RETURN","CONTACTNAME","Dileep Essentials Pvt Ltd Jaipur Store","OWN_STORE",10,False,"FY25-26 returns; store identity unresolved"))
CA.append(("ERP_RETAIL_RETURN","CONTACTNAME","Dileep Essentials Pvt Ltd Lucknow","OWN_STORE",10,False,"FY25-26 returns; location unresolved"))
for v,c in [("Shopify","WEBSITE"),("Nykaa Fashion","NYKAA_FASHION"),("Amazon_SC_Easyship","AMAZON_SELF_SHIP"),("Myntra","MYNTRA"),("Tata Cliq Mall","TATA_CLIQ_MALL")]:
    CA.append(("WMS_DISPATCH","Site Location",v,c,10,False,"From the pasted dispatch sample; full list to check on the real export"))
# Seen on the full dispatch export (Apr 2025 - 15 Sep 2026, received Oct 2026). Names match the channel master one to one.
for v,c in [("Tata Cliq","TATA_CLIQ"),("Tata Cliq Mall - Furniture","TATA_CLIQ_MALL_FURNITURE"),("Pepperfry","PEPPERFRY"),("Nykaa","NYKAA"),
            ("FNP E Retail","FNP"),("FlipkartV3_MultiWH","FLIPKART"),("Amazon Flex","AMAZON_SELLER_FLEX")]:
    CA.append(("WMS_DISPATCH","Site Location",v,c,10,False,"Seen on the full dispatch export (Oct 2026); to confirm with the business"))
CA.append(("WMS_DISPATCH","Site Location","Ellementry International","EXPORT_B2C",10,True,"Business confirmed (Oct 2026): B2C export"))
UNRESOLVED.append(("WMS_DISPATCH","Site Location","Ellementry International","4 dispatches Apr 2025 - Sep 2026","Which channel is 'Ellementry International'? Left Unknown until answered"))
CA.append(("BLINKIT_SALES","(whole source)","*","BLINKIT",100,True,"Every row of the Blinkit sales file is Blinkit"))
CA.append(("INSTAMART_SALES","(whole source)","*","INSTAMART",100,True,"Every row of the Instamart sales file is Instamart"))
PTC = [("B2B_CUSTOMER","B2B",True),("FRANCHISE_PARTNER","FRANCHISE",True),("SIS_PARTNER","SIS",True),("GROUP_EXPORT","EXPORT_VIA_DILEEP",True),
       ("EXPORT_CUSTOMER","EXPORT_DIRECT",False),("EMPLOYEE","INTERNAL_EMPLOYEE",True)]

# ---------------------------------------------------------------- FY25-26 exports (received Oct 2026)
# 1. Billing locations (CHANNELNAME) are exact ERP location names: every name in the location master is accepted for each sales /
#    returns source, not only the ones the Apr-Sep 2026 samples happened to contain.
for src in ("ERP_RETAIL_SALES","ERP_DOMESTIC_SALES","ERP_DOMESTIC_RETURN"):
    have = {a[2] for a in LA if a[0] == src and a[1] == "CHANNELNAME"}
    for n, code in erp_names.items():
        if n not in have:
            LA.append((src,"CHANNELNAME",n,code,False,"Exact ERP location name"))
# 2. Long contact names resolved by data: in the FY25-26 retail sales each of these contacts is billed at ONE ERP location only
#    (lines: Lucknow 1,166 / Jaipur Store 300 / Bagru 226 / Mumbai PPOB 45 / Delhi 32 / CG Road 11, all 100%).
billed_at = {"Dileep Essentials Pvt Ltd Lucknow":("DEPL_LUCKNOW",1166),"Dileep Essentials Pvt Ltd Jaipur Store":("STORE_JPR_MEERAKI",300),
             "Dileep Essentials Pvt Ltd Bagru":("POPUP_BAGRU",226),"Dileep Essentials Pvt Ltd Mumbai PPOB":("DEPL_MUMBAI_PPOB",45),
             "Dileep Essentials Pvt Ltd Delhi":("DEPL_DELHI",32),"Dileep Essentials Pvt Ltd CG Road Ahmedabad":("STORE_AMD_CGROAD",11)}
for src in ("ERP_STOCK_TRANSFER_OUT","ERP_STOCK_TRANSFER_IN","ERP_RETAIL_RETURN"):
    have = {a[2] for a in LA if a[0] == src and a[1] == "CONTACTNAME"}
    for v,(code,n) in billed_at.items():
        if v not in have:
            LA.append((src,"CONTACTNAME",v,code,False,f"FY25-26 retail sales bill this contact only at this ERP location ({n} lines, 100%)"))
for v in ("Dileep Essentials Pvt Ltd Bagru","Dileep Essentials Pvt Ltd CG Road Ahmedabad"):   # both are shops (popup store, own store)
    CA.append(("ERP_RETAIL_SALES","CONTACTNAME",v,"OWN_STORE",10,False,"FY25-26 sales billed at an own store / popup location"))
    CA.append(("ERP_RETAIL_RETURN","CONTACTNAME",v,"OWN_STORE",10,False,"FY25-26 returns at an own store / popup location"))
UNRESOLVED = [u for u in UNRESOLVED if u[2] not in billed_at and u[2] != "BAG/DC"]
UNRESOLVED.append(("ERP_RETAIL_SALES","CONTACTNAME","Dileep Essentials Pvt Ltd Mumbai PPOB / Delhi",
                   "FY25-26 retail sales billed at DEPL Mumbai PPOB / DEPL Delhi","Which sales channel are these (own store? B2B?) Location is known; channel left Unknown"))

# ---------------------------------------------------------------- write CSV seeds
def w(name, header, rows):
    with open(os.path.join(OUT,name),"w",newline="",encoding="utf-8") as f:
        cw=csv.writer(f, lineterminator="\n"); cw.writerow(header)
        for r in rows: cw.writerow(["" if x is None else x for x in r])
b = lambda x: "true" if x else "false"
def loc_rule(code):
    if code in ("BAGRU_WH","HEAD_OFFICE"): return "BR-016"
    if code.startswith("FBA_"): return "BR-019"
    if code == "EMPLOYEE_EXHIBITION": return "BR-029"
    if code.startswith("CONSIGN_"): return "BR-022"
    return ""
def loc_alias_rule(src, field, code):
    if src == "WMS_DISPATCH": return "BR-017"
    if src == "ERP_RETAIL_RETURN" and code.startswith("FBA_"): return "BR-009"
    return loc_rule(code)
def chan_alias_rule(src, code):
    if src not in ("ERP_RETAIL_SALES","ERP_RETAIL_RETURN"): return "BR-018" if src == "BLINKIT_SALES" else ""
    return {"AMAZON_FBA":"BR-008","EXPORT_VIA_DILEEP":"BR-007"}.get(code, "BR-006")
FULFIL = {"WEBSITE":("SELF_SHIP",False),"AMAZON_FBA":("AMAZON_FBA",False),"AMAZON_SELF_SHIP":("SELF_SHIP",False),
          "AMAZON_SELLER_FLEX":("SELLER_FLEX",False),"OWN_STORE":("STORE",False),"B2B":("NONE",False),
          "FRANCHISE":("PARTNER",True),"SIS":("PARTNER",True),"BLINKIT":("PARTNER",True),"INSTAMART":("PARTNER",True),
          "EXPORT_VIA_DILEEP":("NONE",False),"EXPORT_DIRECT":("NONE",False),"INTERNAL_EMPLOYEE":("NONE",False)}
fulfil = lambda c: FULFIL.get(c, ("SELF_SHIP",False))   # marketplaces: shipped from Bagru (WMS shows Myntra, Nykaa, Tata Cliq)
w("ref_location_master.csv",["location_code","erp_location_name","location_name","location_type","operated_by","gst_state_code","city","is_stock_holding",
  "is_sellable_stock","inventory_system_of_record","is_active","is_confirmed","notes","rule_id","opening_date","closing_date"],
  [(r[0],r[1],r[2],r[3],r[4],r[5],r[6],b(r[7]),b(r[8]),r[9],b(r[10]),b(r[11]),(r[13]+(" | OPEN: "+r[14] if r[14] else ""))[:500],loc_rule(r[0]),"","") for r in L])
w("ref_location_alias.csv",["source_name","source_field","source_value","location_code","is_confirmed","notes","rule_id"],[(a[0],a[1],a[2],a[3],b(a[4]),a[5],loc_alias_rule(a[0],a[1],a[3])) for a in LA])
w("ref_document_prefix_location.csv",["source_name","doc_prefix","location_code","is_confirmed","notes","rule_id"],
  [("ERP_STOCK_TRANSFER_OUT",p,c,"false",f"Derived: {n} linked receipts all name this sender (100%)",loc_rule(c)) for p,c,n in PFX])
w("ref_channel_master.csv",["channel_code","channel_name","sub_channel_name","channel_group","is_active","is_confirmed","notes","fulfilment_model","is_sale_or_return"],
  [(c[0],c[1],c[2],c[3],"true",b(c[4]),c[5],fulfil(c[0])[0],b(fulfil(c[0])[1])) for c in C])
w("ref_channel_alias.csv",["source_name","source_field","source_value","channel_code","priority","is_confirmed","notes","rule_id"],
  [(a[0],a[1],a[2],a[3],a[4],b(a[5]),a[6],chan_alias_rule(a[0],a[3])) for a in CA])
# ref_partner_type_channel.csv is maintained directly (rule ids); not generated

import json; json.dump({"L":L,"LA":LA,"PFX":PFX,"C":C,"CA":CA,"PTC":PTC,"UNRESOLVED":UNRESOLVED}, open(os.path.join(OUT,"_mapping_model.json"),"w"), default=str)
print(f"locations={len(L)} location_aliases={len(LA)} prefixes={len(PFX)} channels={len(C)} channel_aliases={len(CA)} unresolved={len(UNRESOLVED)}")
