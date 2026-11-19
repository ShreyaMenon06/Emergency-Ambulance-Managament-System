-- =====================================================================
-- Emergency Ambulance Management System : test queries
-- Run one at a time in SQL Workshop > SQL Commands (each query ends with a semicolon).
-- Each query shows one relationship or notation of the ER diagram.
-- =====================================================================

-- Q1. Every emergency call with the agent who handled it and the customer who called   (handled_by, calls)
SELECT c.call_id, c.call_time, c.call_type, c.urgency_level, c.is_false_alarm,
       a.first_name || ' ' || a.last_name AS handled_by,
       cu.first_name || ' ' || cu.last_name AS caller
FROM   emergency_call c
JOIN   call_center_agent a ON a.agent_id = c.agent_id
LEFT   JOIN customer cu    ON cu.customer_id = c.customer_id
ORDER  BY c.call_time;

-- Q2. Number of calls handled by each agent                          (handled_by)
SELECT a.agent_id, a.first_name || ' ' || a.last_name AS agent, COUNT(c.call_id) AS calls_handled
FROM   call_center_agent a LEFT JOIN emergency_call c ON c.agent_id = a.agent_id
GROUP  BY a.agent_id, a.first_name, a.last_name
ORDER  BY a.agent_id;

-- Q3. Every dispatch with its call, agent, ambulance, driver, paramedic and the derived response time
--     (results_in, initiates, uses, drives, attends, derived attribute)
SELECT d.dispatch_id, d.status, d.call_id, d.dispatch_time, d.arrival_time, d.response_time AS response_minutes,
       a.first_name || ' ' || a.last_name  AS initiated_by,
       m.vehicle_no,
       dr.first_name || ' ' || dr.last_name AS driver,
       p.first_name || ' ' || p.last_name   AS paramedic
FROM   dispatch d
JOIN   call_center_agent a ON a.agent_id = d.agent_id
JOIN   ambulance m         ON m.ambulance_id = d.ambulance_id
JOIN   driver dr           ON dr.driver_id = d.driver_id
LEFT   JOIN paramedic p    ON p.paramedic_id = d.paramedic_id
ORDER  BY d.dispatch_id;

-- Q4. Average response time per ambulance                            (derived attribute)
SELECT m.vehicle_no, COUNT(*) AS dispatches, ROUND(AVG(d.response_time), 2) AS avg_response_minutes
FROM   dispatch d JOIN ambulance m ON m.ambulance_id = d.ambulance_id
WHERE  d.response_time IS NOT NULL
GROUP  BY m.vehicle_no
ORDER  BY avg_response_minutes;

-- Q5. Patients with the dispatch that carried them and the hospital   (transports, taken_to)
SELECT p.patient_id, p.first_name || ' ' || p.last_name AS patient, p.blood_group,
       d.dispatch_id, h.hospital_name, h.branch_name
FROM   patient p
JOIN   dispatch d ON d.dispatch_id = p.dispatch_id
JOIN   hospital h ON h.hospital_id = p.hospital_id
ORDER  BY p.patient_id;

-- Q6. Patients' known allergies                                      (multivalued attribute, table PATIENT_ALLERGY)
SELECT p.patient_id, p.first_name || ' ' || p.last_name AS patient, a.allergy AS known_allergy
FROM   patient p
JOIN   patient_allergy a ON a.patient_id = p.patient_id
ORDER  BY p.patient_id, a.allergy;

-- Q7. Vitals log of a patient (weak entity, key = patient_id + log_time; blood_pressure composite)
SELECT v.patient_id, v.log_time, v.temperature, v.o2,
       v.systolic || '/' || v.diastolic AS blood_pressure, v.heart_rate
FROM   patient_vitals_log v
ORDER  BY v.patient_id, v.log_time;

-- Q8. Paramedics attending each ambulance                            (attended_by, 1:N)
SELECT m.vehicle_no, p.first_name || ' ' || p.last_name AS paramedic, p.certification_level
FROM   paramedic p JOIN ambulance m ON m.ambulance_id = p.ambulance_id
ORDER  BY m.vehicle_no, paramedic;

-- Q9. HR record of every agent, driver and paramedic: salary, leave policy, staff insurance, days present in the last 30 days (HR handles, 1:1 per person)
SELECT 'Agent' AS staff_type, a.first_name || ' ' || a.last_name AS name,
       h.hr_id, h.salary, h.leave_policy, h.staff_insurance,
       (SELECT COUNT(*) FROM hr_attendance t WHERE t.hr_id = h.hr_id AND t.status IN ('Present','Half Day') AND t.att_date >= TRUNC(SYSDATE) - 30) AS present_days_30
FROM   call_center_agent a JOIN hr h ON h.hr_id = a.hr_id
UNION ALL
SELECT 'Driver', d.first_name || ' ' || d.last_name,
       h.hr_id, h.salary, h.leave_policy, h.staff_insurance,
       (SELECT COUNT(*) FROM hr_attendance t WHERE t.hr_id = h.hr_id AND t.status IN ('Present','Half Day') AND t.att_date >= TRUNC(SYSDATE) - 30) AS present_days_30
FROM   driver d JOIN hr h ON h.hr_id = d.hr_id
UNION ALL
SELECT 'Paramedic', p.first_name || ' ' || p.last_name,
       h.hr_id, h.salary, h.leave_policy, h.staff_insurance,
       (SELECT COUNT(*) FROM hr_attendance t WHERE t.hr_id = h.hr_id AND t.status IN ('Present','Half Day') AND t.att_date >= TRUNC(SYSDATE) - 30) AS present_days_30
FROM   paramedic p JOIN hr h ON h.hr_id = p.hr_id
ORDER  BY 1, 3;

-- Q10. Insurance policy of every ambulance and days left before it expires   (insured_by; Oracle only because of SYSDATE)
SELECT m.vehicle_no, i.policy_no, i.insurer, i.policy_type, i.start_date, i.expiry_date, i.premium,
       TRUNC(i.expiry_date - SYSDATE) AS days_left
FROM   ambulance_insurance i JOIN ambulance m ON m.ambulance_id = i.ambulance_id
ORDER  BY i.expiry_date;

-- Q11. Maintenance history of each ambulance, with workshop and the Fleet Manager who handled it   (undergoes)
SELECT m.vehicle_no, l.maintenance_date, l.maintenance_type, l.workshop, l.handled_by, l.cost, l.next_due_date
FROM   ambulance_maintenance_log l JOIN ambulance m ON m.ambulance_id = l.ambulance_id
ORDER  BY m.vehicle_no, l.maintenance_date;

-- Q12. Equipment carried by each ambulance                            (holds, weak entity)
SELECT m.vehicle_no, e.equipment_no, e.equipment_name, e.equipment_condition, e.expiry_date, e.quantity
FROM   ambulance_equipment e JOIN ambulance m ON m.ambulance_id = e.ambulance_id
ORDER  BY m.vehicle_no, e.equipment_no;

-- Q13. GPS location log of an ambulance                               (records, weak entity)
SELECT m.vehicle_no, l.log_time, l.speed, l.latitude, l.longitude
FROM   location_log l JOIN ambulance m ON m.ambulance_id = l.ambulance_id
ORDER  BY m.vehicle_no, l.log_time;

-- Q14. Customers, the agent who entered them and the hospital that notified (enters, notifies)
SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer,
       a.first_name || ' ' || a.last_name AS entered_by,
       h.hospital_name AS notified_by_hospital
FROM   customer c
JOIN   call_center_agent a ON a.agent_id = c.agent_id
LEFT   JOIN hospital h     ON h.hospital_id = c.hospital_id
ORDER  BY c.customer_id;

-- Q15. Customer phone numbers and e-mails                            (multivalued attributes, tables CUSTOMER_PHONE and CUSTOMER_EMAIL)
SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer, p.phone_no
FROM   customer c
JOIN   customer_phone p ON p.customer_id = c.customer_id
ORDER  BY c.customer_id, p.phone_no;

SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer, e.email
FROM   customer c
JOIN   customer_email e ON e.customer_id = c.customer_id
ORDER  BY c.customer_id, e.email;

-- Q16. Bills with the paying customer, the trip they charge and the notifying agent   (pays, billed_for, notifies)
SELECT b.billing_id, b.receipt, b.bill_date, b.payment_mode, b.distance_km, b.base_fare, b.total_amount,
       b.payment_status, b.dispatch_id,
       c.first_name || ' ' || c.last_name AS customer,
       a.first_name || ' ' || a.last_name AS notified_by
FROM   billing b
JOIN   customer c ON c.customer_id = b.customer_id
LEFT   JOIN call_center_agent a ON a.agent_id = b.agent_id
ORDER  BY b.billing_id;

-- Q17. Revenue by payment mode
SELECT payment_mode, COUNT(*) AS bills, SUM(total_amount) AS revenue
FROM   billing
GROUP  BY payment_mode
ORDER  BY revenue DESC;

-- Q18. Hospitals with free beds, their contact agent and phone numbers (contacts, multivalued phone_no in HOSPITAL_PHONE)
SELECT h.hospital_name, h.branch_name, h.beds_available,
       a.first_name || ' ' || a.last_name AS contact_agent, hp.phone_no
FROM   hospital h
LEFT   JOIN call_center_agent a ON a.agent_id = h.agent_id
JOIN   hospital_phone hp ON hp.hospital_id = h.hospital_id
ORDER  BY h.beds_available DESC, h.hospital_name;

-- Q19. Follow one emergency from the call to the bill                (call -> dispatch -> patient -> hospital -> bill)
SELECT c.call_id, c.call_type, d.dispatch_id, m.vehicle_no,
       p.first_name || ' ' || p.last_name AS patient, h.hospital_name,
       b.receipt, b.total_amount, b.payment_status
FROM   emergency_call c
JOIN   dispatch d  ON d.call_id = c.call_id
JOIN   ambulance m ON m.ambulance_id = d.ambulance_id
JOIN   patient p   ON p.dispatch_id = d.dispatch_id
JOIN   hospital h  ON h.hospital_id = p.hospital_id
LEFT   JOIN billing b ON b.dispatch_id = d.dispatch_id
ORDER  BY c.call_id;

-- Q20. False-alarm calls (these have no dispatch)
SELECT call_id, call_time, pick_location, call_type, description
FROM   emergency_call
WHERE  is_false_alarm = 'Y';

-- Q21. Ambulances that are not available right now
SELECT ambulance_id, vehicle_no, model, status, current_location
FROM   ambulance
WHERE  status <> 'Available';

-- Q22. Derived attributes age and experience (views; Oracle only because they use SYSDATE)
SELECT agent_id, first_name, last_name, age, experience FROM v_agent;
SELECT driver_id, first_name, last_name, age, experience FROM v_driver;
SELECT paramedic_id, first_name, last_name, age, experience FROM v_paramedic;
SELECT patient_id, first_name, last_name, age FROM v_patient;

-- Q23. Drivers whose licence expires within the next 2 years (Oracle: ADD_MONTHS)
SELECT driver_id, first_name, last_name, license_no, license_expiry
FROM   driver
WHERE  license_expiry < ADD_MONTHS(SYSDATE, 24)
ORDER  BY license_expiry;

-- Q24. Row count of every table (checks the whole script loaded)
SELECT 'HR' AS table_name, COUNT(*) AS row_count FROM hr
UNION ALL SELECT 'CALL_CENTER_AGENT', COUNT(*) FROM call_center_agent
UNION ALL SELECT 'AMBULANCE', COUNT(*) FROM ambulance
UNION ALL SELECT 'AMBULANCE_INSURANCE', COUNT(*) FROM ambulance_insurance
UNION ALL SELECT 'HOSPITAL', COUNT(*) FROM hospital
UNION ALL SELECT 'CUSTOMER', COUNT(*) FROM customer
UNION ALL SELECT 'EMERGENCY_CALL', COUNT(*) FROM emergency_call
UNION ALL SELECT 'DRIVER', COUNT(*) FROM driver
UNION ALL SELECT 'PARAMEDIC', COUNT(*) FROM paramedic
UNION ALL SELECT 'DISPATCH', COUNT(*) FROM dispatch
UNION ALL SELECT 'PATIENT', COUNT(*) FROM patient
UNION ALL SELECT 'BILLING', COUNT(*) FROM billing
UNION ALL SELECT 'PATIENT_VITALS_LOG', COUNT(*) FROM patient_vitals_log
UNION ALL SELECT 'LOCATION_LOG', COUNT(*) FROM location_log
UNION ALL SELECT 'AMBULANCE_MAINTENANCE_LOG', COUNT(*) FROM ambulance_maintenance_log
UNION ALL SELECT 'AMBULANCE_EQUIPMENT', COUNT(*) FROM ambulance_equipment;

-- Q20. Languages spoken by each call-centre agent                    (multivalued attribute, table AGENT_LANGUAGE)
SELECT a.agent_id, a.first_name || ' ' || a.last_name AS agent, l.language
FROM   call_center_agent a
JOIN   agent_language l ON l.agent_id = a.agent_id
ORDER  BY a.agent_id, l.language;
