-- =====================================================================
-- Emergency Ambulance Management System : sample data, version 3
-- Run AFTER 01_schema.sql, in one go (the IDs are generated 1, 2, 3 ... in the order inserted,
-- and the foreign keys below rely on that). Run only once on empty tables; to reload, run 01_schema.sql first.
-- Triggers do part of the work while loading: ambulance status follows the dispatches, hospital beds go down
-- with each patient, payment_status follows amount_paid, and every dispatch gets its status history.
-- After this script run  py -3.12 setup_users.py  to create the logins.
-- The audit trail is emptied at the end, so it starts clean when the application is first used.
-- =====================================================================

-- TARIFF: the price list per type of ambulance
INSERT INTO tariff VALUES ('BLS','Basic Life Support: first aid, oxygen, stretcher',400,20);
INSERT INTO tariff VALUES ('ALS','Advanced Life Support: defibrillator, cardiac monitor',600,28);
INSERT INTO tariff VALUES ('ICU','Intensive care: ventilator, full monitoring',900,40);

-- HR : one record per person: agents (1-3), drivers (4-7), paramedics (8-11). Salary lives only here.
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (32000,24,'24 days per year','Group health and accident cover, valid to 2027-03-31');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (30000,24,'24 days per year','Group health and accident cover, valid to 2027-03-31');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (34000,30,'30 days per year','Group health and accident cover, valid to 2027-03-31');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (28000,24,'24 days per year','Group health and accident cover, valid to 2027-03-31');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (27000,24,'24 days per year','Group health and accident cover, valid to 2027-06-30');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (29000,24,'24 days per year','Group health and accident cover, valid to 2027-01-15');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (26000,24,'24 days per year','Group health and accident cover, valid to 2026-12-31');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (35000,30,'30 days per year','Group health and accident cover, valid to 2027-03-31');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (32000,30,'30 days per year','Group health and accident cover, valid to 2027-06-30');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (36000,30,'30 days per year','Group health and accident cover, valid to 2027-01-15');
INSERT INTO hr (salary,annual_leave_days,leave_policy,staff_insurance) VALUES (30000,30,'30 days per year','Group health and accident cover, valid to 2027-03-31');

-- CALL_CENTER_AGENT (1-3): own HR record (hr_id 1-3)
INSERT INTO call_center_agent (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,shift,agent_role,date_of_joining,hr_id)
  VALUES ('Ravi','K','Kumar',DATE '1995-06-15','111122223333','4 Park Street','Bengaluru','Karnataka','560001','9876500001','Night','Senior Agent',DATE '2021-03-01',1);
INSERT INTO call_center_agent (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,shift,agent_role,date_of_joining,hr_id)
  VALUES ('Meena','S','Iyer',DATE '1998-02-20','111122224444','17 Lake Road','Bengaluru','Karnataka','560034','9876500002','Day','Agent',DATE '2022-08-10',2);
INSERT INTO call_center_agent (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,shift,agent_role,date_of_joining,hr_id)
  VALUES ('Arjun','P','Reddy',DATE '1992-11-05','111122225555','9 Church Street','Bengaluru','Karnataka','560001','9876500003','Evening','Team Lead',DATE '2019-01-14',3);

-- AMBULANCE (1-4): the statuses are set by the dispatch trigger below; the type must exist in TARIFF
INSERT INTO ambulance (model,status,vehicle_no,type_of_ambulance,manufacture_year,current_location) VALUES ('Force Traveller','Available','KA01AB1234','ALS',2022,'Koramangala, Bengaluru');
INSERT INTO ambulance (model,status,vehicle_no,type_of_ambulance,manufacture_year,current_location) VALUES ('Tata Winger','Available','KA01CD5678','BLS',2021,'Indiranagar, Bengaluru');
INSERT INTO ambulance (model,status,vehicle_no,type_of_ambulance,manufacture_year,current_location) VALUES ('Mahindra Bolero','Available','KA02EF9012','ICU',2023,'Hebbal, Bengaluru');
INSERT INTO ambulance (model,status,vehicle_no,type_of_ambulance,manufacture_year,current_location) VALUES ('Force Traveller','Maintenance','KA03GH3456','ALS',2020,'Central Garage, Bengaluru');

-- AMBULANCE_INSURANCE: one policy per ambulance, handled by Admin / Fleet Manager
INSERT INTO ambulance_insurance VALUES ('POL-2026-0001',1,'National Insurance','Comprehensive',DATE '2026-04-01',DATE '2027-03-31',38000);
INSERT INTO ambulance_insurance VALUES ('POL-2026-0002',2,'United India Insurance','Comprehensive',DATE '2026-07-01',DATE '2027-06-30',32000);
INSERT INTO ambulance_insurance VALUES ('POL-2026-0003',3,'New India Assurance','Third party',DATE '2026-01-16',DATE '2027-01-15',15000);
INSERT INTO ambulance_insurance VALUES ('POL-2026-0004',4,'National Insurance','Comprehensive',DATE '2026-01-01',DATE '2026-12-31',36000);

-- HOSPITAL (1-4), contacted by an agent; phone numbers are rows of HOSPITAL_PHONE. The bed numbers are the counts BEFORE the sample patients
-- below are taken in (each patient takes one bed), so they end at 14, 9, 20 and 6.
INSERT INTO hospital (hospital_name,branch_name,street,city,state,pincode,beds_available,latitude,longitude,agent_id) VALUES ('City General Hospital','Hosur Road','5 Hosur Road','Bengaluru','Karnataka','560029',16,12.917000,77.623000,1);
INSERT INTO hospital (hospital_name,branch_name,street,city,state,pincode,beds_available,latitude,longitude,agent_id) VALUES ('Sunrise Medical Centre','Whitefield','22 ITPL Road','Bengaluru','Karnataka','560066',10,12.986000,77.738000,2);
INSERT INTO hospital (hospital_name,branch_name,street,city,state,pincode,beds_available,latitude,longitude,agent_id) VALUES ('Apollo Care','Bannerghatta','154 Bannerghatta Road','Bengaluru','Karnataka','560076',21,12.895000,77.597000,1);
INSERT INTO hospital (hospital_name,branch_name,street,city,state,pincode,beds_available,latitude,longitude,agent_id) VALUES ('St Marys Hospital','Indiranagar','8 100 Feet Road','Bengaluru','Karnataka','560038',7,12.972000,77.641000,3);

-- CUSTOMER (1-5): entered by an agent, optionally notified by a hospital; phone_no and email are lists
INSERT INTO customer (first_name,middle_name,last_name,aadhar,street,city,state,pincode,agent_id,hospital_id) VALUES ('Asha','R','Nair','222233334444','12 MG Road','Bengaluru','Karnataka','560001',1,1);
INSERT INTO customer (first_name,middle_name,last_name,aadhar,street,city,state,pincode,agent_id,hospital_id) VALUES ('Karthik','V','Menon','222233335555','31 Jayanagar 4th Block','Bengaluru','Karnataka','560011',2,3);
INSERT INTO customer (first_name,middle_name,last_name,aadhar,street,city,state,pincode,agent_id,hospital_id) VALUES ('Fatima','A','Khan','222233336666','6 Frazer Town','Bengaluru','Karnataka','560005',1,NULL);
INSERT INTO customer (first_name,middle_name,last_name,aadhar,street,city,state,pincode,agent_id,hospital_id) VALUES ('Rohan','D','Shetty','222233337777','88 Whitefield Main Road','Bengaluru','Karnataka','560066',3,2);
INSERT INTO customer (first_name,middle_name,last_name,aadhar,street,city,state,pincode,agent_id,hospital_id) VALUES ('Lakshmi','N','Rao','222233338888','14 Malleshwaram','Bengaluru','Karnataka','560003',2,4);

-- EMERGENCY_CALL (1-9), handled by an agent, made by a customer (the caller).
-- Call 5 is a false alarm. Calls 8 and 9 are still waiting for an ambulance.
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-10 14:00','YYYY-MM-DD HH24:MI'),'12 MG Road, near Metro Station','Cardiac','N',95,'Critical','Chest pain, patient conscious',1,1);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-10 16:20','YYYY-MM-DD HH24:MI'),'31 Jayanagar 4th Block','Accident','N',140,'High','Two-wheeler collision, leg injury',2,2);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-10 19:45','YYYY-MM-DD HH24:MI'),'6 Frazer Town','Breathing difficulty','N',70,'High','Elderly patient, asthma attack',1,3);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-11 02:10','YYYY-MM-DD HH24:MI'),'88 Whitefield Main Road','Fall','N',110,'Medium','Fall from stairs, suspected fracture',3,4);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-11 08:30','YYYY-MM-DD HH24:MI'),'14 Malleshwaram','Fire','Y',45,'Low','Smoke reported, false alarm',2,5);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-18 18:30','YYYY-MM-DD HH24:MI'),'Hebbal Flyover','Accident','N',120,'Critical','Car and truck collision, two injured',1,5);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-18 18:50','YYYY-MM-DD HH24:MI'),'6 Frazer Town','Stroke','N',85,'High','Sudden weakness on one side, slurred speech',2,3);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-18 19:05','YYYY-MM-DD HH24:MI'),'88 Whitefield Main Road','Pregnancy','N',60,'Medium','Labour pains every 8 minutes',3,4);
INSERT INTO emergency_call (call_time,pick_location,call_type,is_false_alarm,call_duration,urgency_level,description,agent_id,customer_id) VALUES (TO_DATE('2026-11-18 19:12','YYYY-MM-DD HH24:MI'),'12 MG Road, near Metro Station','Cardiac','N',75,'Critical','Collapsed at office, not responding',1,1);

-- The area of each call (latitude, longitude) so the nearest hospital can be offered at dispatch
UPDATE emergency_call SET pick_lat = 12.9756, pick_lon = 77.6067 WHERE call_id IN (1, 9);   -- MG Road
UPDATE emergency_call SET pick_lat = 12.9299, pick_lon = 77.5838 WHERE call_id = 2;          -- Jayanagar
UPDATE emergency_call SET pick_lat = 13.0010, pick_lon = 77.6143 WHERE call_id IN (3, 7);   -- Frazer Town
UPDATE emergency_call SET pick_lat = 12.9698, pick_lon = 77.7500 WHERE call_id IN (4, 8);   -- Whitefield
UPDATE emergency_call SET pick_lat = 13.0035, pick_lon = 77.5710 WHERE call_id = 5;          -- Malleshwaram
UPDATE emergency_call SET pick_lat = 13.0358, pick_lon = 77.5970 WHERE call_id = 6;          -- Hebbal

-- DRIVER (1-4): own HR record (hr_id 4-7)
INSERT INTO driver (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,license_no,license_expiry,driving_experience,date_of_joining,hr_id,ambulance_id)
  VALUES ('Manoj','S','Gowda',DATE '1989-04-12','333344445551','8 Temple Road','Bengaluru','Karnataka','560010','9845100001','KA0120190012345',DATE '2029-04-11',12,DATE '2019-07-01',4,1);
INSERT INTO driver (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,license_no,license_expiry,driving_experience,date_of_joining,hr_id,ambulance_id)
  VALUES ('Imran','A','Pasha',DATE '1990-08-23','333344445552','45 Shivajinagar','Bengaluru','Karnataka','560051','9845100002','KA0220180023456',DATE '2028-08-22',10,DATE '2020-02-10',5,2);
INSERT INTO driver (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,license_no,license_expiry,driving_experience,date_of_joining,hr_id,ambulance_id)
  VALUES ('Suresh','B','Naik',DATE '1985-01-30','333344445553','12 Yeshwanthpur','Bengaluru','Karnataka','560022','9845100003','KA0320150034567',DATE '2027-01-29',15,DATE '2018-05-21',6,3);
INSERT INTO driver (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,license_no,license_expiry,driving_experience,date_of_joining,hr_id,ambulance_id)
  VALUES ('Prakash','T','Kumar',DATE '1993-12-09','333344445554','73 Banashankari','Bengaluru','Karnataka','560070','9845100004','KA0420200045678',DATE '2030-12-08',8,DATE '2021-09-01',7,4);

-- PARAMEDIC (1-4): own HR record (hr_id 8-11), attached to an ambulance
INSERT INTO paramedic (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,certification_no,certification_level,date_of_joining,hr_id,ambulance_id)
  VALUES ('Divya','M','Rao',DATE '1993-09-30','444455556661','22 Lake View','Bengaluru','Karnataka','560034','9845200001','EMT-7781','Advanced',DATE '2020-01-15',8,1);
INSERT INTO paramedic (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,certification_no,certification_level,date_of_joining,hr_id,ambulance_id)
  VALUES ('Nikhil','J','Joshi',DATE '1996-05-18','444455556662','5 Rajajinagar','Bengaluru','Karnataka','560010','9845200002','EMT-7782','Intermediate',DATE '2022-03-07',9,2);
INSERT INTO paramedic (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,certification_no,certification_level,date_of_joining,hr_id,ambulance_id)
  VALUES ('Sneha','K','Pillai',DATE '1994-03-02','444455556663','19 BTM Layout','Bengaluru','Karnataka','560029','9845200003','EMT-7783','Advanced',DATE '2019-11-25',10,3);
INSERT INTO paramedic (first_name,middle_name,last_name,dob,aadhar,street,city,state,pincode,phone_no,certification_no,certification_level,date_of_joining,hr_id,ambulance_id)
  VALUES ('Arun','V','Menon',DATE '1991-07-14','444455556664','61 HSR Layout','Bengaluru','Karnataka','560102','9845200004','EMT-7784','Basic',DATE '2023-06-12',11,1);

-- DISPATCH (1-6): caused by a call, initiated by an agent, uses an ambulance, driven by a driver, attended by a paramedic,
-- goes to a hospital. Dispatches 5 and 6 are running now (To Hospital / En Route).
INSERT INTO dispatch (status,dispatch_time,arrival_time,hospital_arrival_time,call_id,agent_id,ambulance_id,driver_id,paramedic_id,hospital_id) VALUES ('Completed',TO_DATE('2026-11-10 14:03','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-10 14:14','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-10 14:35','YYYY-MM-DD HH24:MI'),1,1,1,1,1,1);
INSERT INTO dispatch (status,dispatch_time,arrival_time,hospital_arrival_time,call_id,agent_id,ambulance_id,driver_id,paramedic_id,hospital_id) VALUES ('Completed',TO_DATE('2026-11-10 16:24','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-10 16:40','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-10 17:05','YYYY-MM-DD HH24:MI'),2,2,2,2,2,3);
INSERT INTO dispatch (status,dispatch_time,arrival_time,hospital_arrival_time,call_id,agent_id,ambulance_id,driver_id,paramedic_id,hospital_id) VALUES ('Completed',TO_DATE('2026-11-10 19:48','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-10 19:58','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-10 20:20','YYYY-MM-DD HH24:MI'),3,1,3,3,3,1);
INSERT INTO dispatch (status,dispatch_time,arrival_time,hospital_arrival_time,call_id,agent_id,ambulance_id,driver_id,paramedic_id,hospital_id) VALUES ('Completed',TO_DATE('2026-11-11 02:14','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-11 02:31','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-11 02:58','YYYY-MM-DD HH24:MI'),4,3,2,4,2,2);
INSERT INTO dispatch (status,dispatch_time,arrival_time,hospital_arrival_time,call_id,agent_id,ambulance_id,driver_id,paramedic_id,hospital_id) VALUES ('To Hospital',TO_DATE('2026-11-18 18:33','YYYY-MM-DD HH24:MI'),TO_DATE('2026-11-18 18:44','YYYY-MM-DD HH24:MI'),NULL,6,1,1,1,4,4);
INSERT INTO dispatch (status,dispatch_time,arrival_time,hospital_arrival_time,call_id,agent_id,ambulance_id,driver_id,paramedic_id,hospital_id) VALUES ('En Route',TO_DATE('2026-11-18 18:53','YYYY-MM-DD HH24:MI'),NULL,NULL,7,2,3,3,3,4);

-- The trigger wrote a history row for each dispatch with the time of loading. Replace it with the real times of each step.
DELETE FROM dispatch_status_log;
INSERT INTO dispatch_status_log (dispatch_id,status,changed_at,changed_by) SELECT dispatch_id,'En Route',CAST(dispatch_time AS TIMESTAMP),'agent_user' FROM dispatch;
INSERT INTO dispatch_status_log (dispatch_id,status,changed_at,changed_by) SELECT dispatch_id,'At Scene',CAST(arrival_time AS TIMESTAMP),'driver_user' FROM dispatch WHERE arrival_time IS NOT NULL;
INSERT INTO dispatch_status_log (dispatch_id,status,changed_at,changed_by) SELECT dispatch_id,'To Hospital',CAST(arrival_time + 8/1440 AS TIMESTAMP),'driver_user' FROM dispatch WHERE arrival_time IS NOT NULL AND hospital_id IS NOT NULL;
INSERT INTO dispatch_status_log (dispatch_id,status,changed_at,changed_by) SELECT dispatch_id,'At Hospital',CAST(hospital_arrival_time AS TIMESTAMP),'driver_user' FROM dispatch WHERE hospital_arrival_time IS NOT NULL;
INSERT INTO dispatch_status_log (dispatch_id,status,changed_at,changed_by) SELECT dispatch_id,'Completed',CAST(hospital_arrival_time + 10/1440 AS TIMESTAMP),'agent_user' FROM dispatch WHERE status = 'Completed';

-- PATIENT (1-5): transported by a dispatch, taken to a hospital (takes one bed); allergies are rows of PATIENT_ALLERGY
INSERT INTO patient (first_name,middle_name,last_name,dob,blood_group,gender,chief_complaint,dispatch_id,hospital_id) VALUES ('Suresh','K','Nair',DATE '1961-02-18','B+','Male','Chest pain, sweating',1,1);
INSERT INTO patient (first_name,middle_name,last_name,dob,blood_group,gender,chief_complaint,dispatch_id,hospital_id) VALUES ('Ananya','M','Menon',DATE '2001-07-09','O+','Female','Leg injury after collision',2,3);
INSERT INTO patient (first_name,middle_name,last_name,dob,blood_group,gender,chief_complaint,dispatch_id,hospital_id) VALUES ('Hameed','A','Khan',DATE '1948-03-21','A+','Male','Asthma attack, difficulty breathing',3,1);
INSERT INTO patient (first_name,middle_name,last_name,dob,blood_group,gender,chief_complaint,dispatch_id,hospital_id) VALUES ('Vikram','S','Shetty',DATE '1975-09-12','AB+','Male','Suspected fracture after fall',4,2);
INSERT INTO patient (first_name,middle_name,last_name,dob,blood_group,gender,chief_complaint,dispatch_id,hospital_id) VALUES ('Padma','L','Rao',DATE '1969-12-01','O-','Female','Head injury, conscious',5,4);

-- MULTIVALUED ATTRIBUTES (one value per row): agent languages, hospital phones, customer phones and emails, patient allergies
INSERT INTO agent_language (agent_id, language) VALUES (1,'English');
INSERT INTO agent_language (agent_id, language) VALUES (1,'Kannada');
INSERT INTO agent_language (agent_id, language) VALUES (2,'English');
INSERT INTO agent_language (agent_id, language) VALUES (2,'Hindi');
INSERT INTO agent_language (agent_id, language) VALUES (2,'Tamil');
INSERT INTO agent_language (agent_id, language) VALUES (3,'English');
INSERT INTO agent_language (agent_id, language) VALUES (3,'Telugu');
INSERT INTO hospital_phone (hospital_id, phone_no) VALUES (1,'08040001000');
INSERT INTO hospital_phone (hospital_id, phone_no) VALUES (1,'08040001001');
INSERT INTO hospital_phone (hospital_id, phone_no) VALUES (2,'08040002000');
INSERT INTO hospital_phone (hospital_id, phone_no) VALUES (3,'08040003000');
INSERT INTO hospital_phone (hospital_id, phone_no) VALUES (4,'08040004000');
INSERT INTO customer_phone (customer_id, phone_no) VALUES (1,'9812300001');
INSERT INTO customer_phone (customer_id, phone_no) VALUES (1,'9812300011');
INSERT INTO customer_phone (customer_id, phone_no) VALUES (2,'9812300002');
INSERT INTO customer_phone (customer_id, phone_no) VALUES (3,'9812300003');
INSERT INTO customer_phone (customer_id, phone_no) VALUES (4,'9812300004');
INSERT INTO customer_phone (customer_id, phone_no) VALUES (5,'9812300005');
INSERT INTO customer_email (customer_id, email) VALUES (1,'asha.nair@example.com');
INSERT INTO customer_email (customer_id, email) VALUES (2,'karthik.menon@example.com');
INSERT INTO customer_email (customer_id, email) VALUES (2,'k.menon@work.example.com');
INSERT INTO customer_email (customer_id, email) VALUES (4,'rohan.shetty@example.com');
INSERT INTO customer_email (customer_id, email) VALUES (5,'lakshmi.rao@example.com');
INSERT INTO patient_allergy (patient_id, allergy) VALUES (1,'Penicillin');
INSERT INTO patient_allergy (patient_id, allergy) VALUES (1,'Dust');
INSERT INTO patient_allergy (patient_id, allergy) VALUES (3,'Sulfa drugs');
INSERT INTO patient_allergy (patient_id, allergy) VALUES (5,'Latex');

-- BILLING (1-4): one bill per finished dispatch, paid by a customer, made by the driver / paramedic (billed_by = their hr_id) and seen by the agent.
-- total_amount = base_fare + distance_km x rate of the ambulance type (ALS 600+28/km, BLS 400+20/km, ICU 900+40/km).
-- payment_status is set by the trigger from amount_paid.
INSERT INTO billing (payment_mode,bill_date,receipt,total_amount,amount_paid,distance_km,base_fare,customer_id,dispatch_id,agent_id,billed_by) VALUES ('UPI',DATE '2026-11-10','RCP-0001',950.00,950.00,12.5,600,1,1,1,4);
INSERT INTO billing (payment_mode,bill_date,receipt,total_amount,amount_paid,distance_km,base_fare,customer_id,dispatch_id,agent_id,billed_by) VALUES ('Card',DATE '2026-11-10','RCP-0002',560.00,300.00,8.0,400,2,2,2,5);
INSERT INTO billing (payment_mode,bill_date,receipt,total_amount,amount_paid,distance_km,base_fare,customer_id,dispatch_id,agent_id,billed_by) VALUES ('Cash',DATE '2026-11-10','RCP-0003',1280.00,1280.00,9.5,900,3,3,1,6);
INSERT INTO billing (payment_mode,bill_date,receipt,total_amount,amount_paid,distance_km,base_fare,customer_id,dispatch_id,agent_id,billed_by) VALUES ('UPI',DATE '2026-11-11','RCP-0004',700.00,0,15.0,400,4,4,3,7);

-- Weak entities
INSERT INTO patient_vitals_log VALUES (1,TIMESTAMP '2026-11-10 14:16:00',36.8,94,150,95,112);
INSERT INTO patient_vitals_log VALUES (1,TIMESTAMP '2026-11-10 14:28:00',36.9,96,142,90,104);
INSERT INTO patient_vitals_log VALUES (2,TIMESTAMP '2026-11-10 16:45:00',37.1,98,118,76,96);
INSERT INTO patient_vitals_log VALUES (2,TIMESTAMP '2026-11-10 16:55:00',37.0,98,116,74,90);
INSERT INTO patient_vitals_log VALUES (3,TIMESTAMP '2026-11-10 20:02:00',36.6,89,138,86,118);
INSERT INTO patient_vitals_log VALUES (3,TIMESTAMP '2026-11-10 20:12:00',36.7,93,134,84,108);
INSERT INTO patient_vitals_log VALUES (4,TIMESTAMP '2026-11-11 02:40:00',36.5,97,126,82,88);
INSERT INTO patient_vitals_log VALUES (5,TIMESTAMP '2026-11-18 18:46:00',37.0,95,130,85,92);

INSERT INTO location_log VALUES (1,TIMESTAMP '2026-11-10 14:05:00',42.0,77.620000,12.935000);
INSERT INTO location_log VALUES (1,TIMESTAMP '2026-11-10 14:10:00',48.5,77.594600,12.971600);
INSERT INTO location_log VALUES (1,TIMESTAMP '2026-11-10 14:30:00',55.0,77.580000,12.910000);
INSERT INTO location_log VALUES (2,TIMESTAMP '2026-11-10 16:30:00',38.0,77.640000,12.978000);
INSERT INTO location_log VALUES (2,TIMESTAMP '2026-11-10 16:50:00',45.5,77.580000,12.925000);
INSERT INTO location_log VALUES (3,TIMESTAMP '2026-11-10 19:52:00',50.0,77.590000,13.035000);
INSERT INTO location_log VALUES (3,TIMESTAMP '2026-11-10 20:08:00',47.0,77.570000,12.990000);
INSERT INTO location_log VALUES (1,TIMESTAMP '2026-11-18 18:40:00',40.0,77.610000,12.950000);
INSERT INTO location_log VALUES (1,TIMESTAMP '2026-11-18 18:52:00',52.0,77.595000,12.975000);
INSERT INTO location_log VALUES (3,TIMESTAMP '2026-11-18 18:58:00',46.0,77.590000,13.030000);

INSERT INTO ambulance_maintenance_log VALUES (1,DATE '2026-10-01','Routine service','Oil change and tyre check','Auto Care Service Centre','R. Hegde (Maintenance)',4200,DATE '2027-01-01');
INSERT INTO ambulance_maintenance_log VALUES (1,DATE '2026-08-10','Tyre replacement','Front tyres replaced','Auto Care Service Centre','R. Hegde (Maintenance)',12000,DATE '2027-02-10');
INSERT INTO ambulance_maintenance_log VALUES (2,DATE '2026-09-15','Brake service','Brake pads replaced','City Motors Workshop','R. Hegde (Maintenance)',6800,DATE '2026-12-15');
INSERT INTO ambulance_maintenance_log VALUES (3,DATE '2026-10-20','Routine service','Filters and fluids','Auto Care Service Centre','R. Hegde (Maintenance)',4500,DATE '2027-01-20');
INSERT INTO ambulance_maintenance_log VALUES (4,DATE '2026-11-05','Engine repair','Gearbox repair, in garage','Central Garage','R. Hegde (Maintenance)',18500,DATE '2027-02-05');

INSERT INTO ambulance_equipment VALUES (1,1,'Defibrillator','Good',DATE '2028-06-30',1);
INSERT INTO ambulance_equipment VALUES (1,2,'Oxygen Cylinder','Good',DATE '2027-03-15',2);
INSERT INTO ambulance_equipment VALUES (1,3,'Stretcher','Good',NULL,1);
INSERT INTO ambulance_equipment VALUES (2,1,'Oxygen Cylinder','Fair',DATE '2026-12-20',2);
INSERT INTO ambulance_equipment VALUES (2,2,'First Aid Kit','Good',DATE '2027-05-01',3);
INSERT INTO ambulance_equipment VALUES (3,1,'Ventilator','Good',DATE '2029-01-10',1);
INSERT INTO ambulance_equipment VALUES (3,2,'Cardiac Monitor','Good',DATE '2028-09-01',1);
INSERT INTO ambulance_equipment VALUES (4,1,'Defibrillator','Needs Repair',DATE '2026-12-01',1);

-- HR_ATTENDANCE: the last 14 days for all 11 staff (hr_id 1-11). Everybody is Present, with a few exceptions below.
INSERT INTO hr_attendance (hr_id, att_date, status)
  SELECT h.hr_id, TRUNC(SYSDATE) - d.n, 'Present'
  FROM hr h, (SELECT LEVEL AS n FROM dual CONNECT BY LEVEL <= 14) d
  WHERE TO_CHAR(TRUNC(SYSDATE) - d.n, 'DY', 'NLS_DATE_LANGUAGE=ENGLISH') <> 'SUN';
UPDATE hr_attendance SET status = 'Absent'   WHERE hr_id = 7  AND att_date = TRUNC(SYSDATE) - 3;
UPDATE hr_attendance SET status = 'Half Day' WHERE hr_id = 4  AND att_date = TRUNC(SYSDATE) - 5;
UPDATE hr_attendance SET status = 'On Leave' WHERE hr_id = 2  AND att_date BETWEEN TRUNC(SYSDATE) - 9 AND TRUNC(SYSDATE) - 8;
UPDATE hr_attendance SET status = 'Absent'   WHERE hr_id = 11 AND att_date IN (TRUNC(SYSDATE) - 6, TRUNC(SYSDATE) - 2);

-- HR_LEAVE: approved, rejected and waiting requests
INSERT INTO hr_leave (hr_id,leave_type,start_date,end_date,reason,status,applied_on,decided_by,decided_on)
  VALUES (2,'Casual',TRUNC(SYSDATE)-9,TRUNC(SYSDATE)-8,'Family function','Approved',TRUNC(SYSDATE)-15,'hr_user',TRUNC(SYSDATE)-14);
INSERT INTO hr_leave (hr_id,leave_type,start_date,end_date,reason,status,applied_on,decided_by,decided_on)
  VALUES (5,'Sick',DATE '2026-09-02',DATE '2026-09-04','Fever','Approved',DATE '2026-09-02','hr_user',DATE '2026-09-02');
INSERT INTO hr_leave (hr_id,leave_type,start_date,end_date,reason,status,applied_on,decided_by,decided_on)
  VALUES (9,'Earned',DATE '2026-10-12',DATE '2026-10-16','Trip home','Rejected',DATE '2026-10-01','hr_user',DATE '2026-10-03');
INSERT INTO hr_leave (hr_id,leave_type,start_date,end_date,reason)
  VALUES (6,'Casual',TRUNC(SYSDATE)+4,TRUNC(SYSDATE)+5,'Personal work');
INSERT INTO hr_leave (hr_id,leave_type,start_date,end_date,reason)
  VALUES (10,'Earned',TRUNC(SYSDATE)+10,TRUNC(SYSDATE)+16,'Wedding in the family');

-- The audit trail starts empty: the loading above is not a user's work.
DELETE FROM audit_log;

COMMIT;
