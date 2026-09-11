
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
DROP TABLE IF EXISTS `AccessLevel`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `AccessLevel` (
  `AccessID` int NOT NULL AUTO_INCREMENT,
  `AccessRole` varchar(255) NOT NULL,
  `AccessDescription` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`AccessID`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Account`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Account` (
  `AccountID` int NOT NULL AUTO_INCREMENT,
  `AccountCode` varchar(20) NOT NULL,
  `AccountTitle` varchar(255) NOT NULL,
  `AccountDescription` longtext,
  `IsActive` int NOT NULL,
  PRIMARY KEY (`AccountID`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `AuditLog`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `AuditLog` (
  `LogID` int NOT NULL AUTO_INCREMENT,
  `Action` varchar(50) NOT NULL,
  `TableName` varchar(50) NOT NULL,
  `RecordID` int NOT NULL,
  `OldValue` json DEFAULT NULL,
  `NewValue` json DEFAULT NULL,
  `Timestamp` datetime(6) NOT NULL,
  `EmployeeID` int NOT NULL,
  PRIMARY KEY (`LogID`),
  KEY `AuditLog_EmployeeID_e1e49cd8_fk_Employee_EID` (`EmployeeID`),
  CONSTRAINT `AuditLog_EmployeeID_e1e49cd8_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=222 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `BusinessCategory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `BusinessCategory` (
  `CategoryID` int NOT NULL AUTO_INCREMENT,
  `CategoryName` varchar(255) NOT NULL,
  `IsProductive` int NOT NULL,
  `IsActive` int NOT NULL,
  `IsPayable` tinyint(1) NOT NULL,
  PRIMARY KEY (`CategoryID`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `BusinessEntry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `BusinessEntry` (
  `BusinessEntryID` int NOT NULL AUTO_INCREMENT,
  `DateWorked` date NOT NULL,
  `ShiftType` varchar(5) DEFAULT NULL,
  `HoursWorked` decimal(5,2) NOT NULL,
  `EntryDescription` longtext,
  `LineStatus` varchar(15) NOT NULL,
  `ApprovedAt` datetime(6) DEFAULT NULL,
  `SupervisorNote` longtext,
  `ApprovedBy` int DEFAULT NULL,
  `BusinessCategoryID` int DEFAULT NULL,
  `LeaveTypeID` int DEFAULT NULL,
  `BusinessHeaderID` int NOT NULL,
  PRIMARY KEY (`BusinessEntryID`),
  KEY `BusinessEntry_ApprovedBy_f3583a2c_fk_Employee_EID` (`ApprovedBy`),
  KEY `BusinessEntry_BusinessCategoryID_3e688a41_fk_BusinessC` (`BusinessCategoryID`),
  KEY `BusinessEntry_LeaveTypeID_f335acd9_fk_LeaveType_LeaveTypeID` (`LeaveTypeID`),
  KEY `BusinessEntry_BusinessHeaderID_d142feac_fk_BusinessH` (`BusinessHeaderID`),
  CONSTRAINT `BusinessEntry_ApprovedBy_f3583a2c_fk_Employee_EID` FOREIGN KEY (`ApprovedBy`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `BusinessEntry_BusinessCategoryID_3e688a41_fk_BusinessC` FOREIGN KEY (`BusinessCategoryID`) REFERENCES `BusinessCategory` (`CategoryID`),
  CONSTRAINT `BusinessEntry_BusinessHeaderID_d142feac_fk_BusinessH` FOREIGN KEY (`BusinessHeaderID`) REFERENCES `BusinessHeader` (`BusinessHeaderID`),
  CONSTRAINT `BusinessEntry_LeaveTypeID_f335acd9_fk_LeaveType_LeaveTypeID` FOREIGN KEY (`LeaveTypeID`) REFERENCES `LeaveType` (`LeaveTypeID`)
) ENGINE=InnoDB AUTO_INCREMENT=31 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `BusinessHeader`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `BusinessHeader` (
  `BusinessHeaderID` int NOT NULL AUTO_INCREMENT,
  `PeriodMonth` int NOT NULL,
  `PeriodYear` int NOT NULL,
  `OverallStatus` varchar(25) NOT NULL,
  `StartedAt` datetime(6) NOT NULL,
  `SubmittedAt` datetime(6) DEFAULT NULL,
  `CompletedAt` datetime(6) DEFAULT NULL,
  `PaidAt` datetime(6) DEFAULT NULL,
  `CrewID` int DEFAULT NULL,
  `EmployeeID` int NOT NULL,
  `PaidBy` int DEFAULT NULL,
  `BH_ApprovedBy_Capt` int DEFAULT NULL,
  PRIMARY KEY (`BusinessHeaderID`),
  KEY `BusinessHeader_CrewID_ba3c6706_fk_Crews_CrewID` (`CrewID`),
  KEY `BusinessHeader_EmployeeID_190e92d6_fk_Employee_EID` (`EmployeeID`),
  KEY `BusinessHeader_PaidBy_7b38e585_fk_Employee_EID` (`PaidBy`),
  KEY `BusinessHeader_BH_ApprovedBy_Capt_7efd7dd6_fk_Employee_EID` (`BH_ApprovedBy_Capt`),
  CONSTRAINT `BusinessHeader_BH_ApprovedBy_Capt_7efd7dd6_fk_Employee_EID` FOREIGN KEY (`BH_ApprovedBy_Capt`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `BusinessHeader_CrewID_ba3c6706_fk_Crews_CrewID` FOREIGN KEY (`CrewID`) REFERENCES `Crews` (`CrewID`),
  CONSTRAINT `BusinessHeader_EmployeeID_190e92d6_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `BusinessHeader_PaidBy_7b38e585_fk_Employee_EID` FOREIGN KEY (`PaidBy`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=31 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Contract`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Contract` (
  `ContractID` int NOT NULL AUTO_INCREMENT,
  `ContractCode` varchar(20) NOT NULL,
  `ContractTitle` varchar(255) NOT NULL,
  `ContractDescription` longtext,
  `IsActive` int NOT NULL,
  PRIMARY KEY (`ContractID`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `ContractAccount`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ContractAccount` (
  `ContractAccountID` int NOT NULL AUTO_INCREMENT,
  `AccountID` int NOT NULL,
  `ContractID` int NOT NULL,
  PRIMARY KEY (`ContractAccountID`),
  UNIQUE KEY `ContractAccount_ContractID_AccountID_f4676e4e_uniq` (`ContractID`,`AccountID`),
  KEY `ContractAccount_AccountID_982fd366_fk_Account_AccountID` (`AccountID`),
  CONSTRAINT `ContractAccount_AccountID_982fd366_fk_Account_AccountID` FOREIGN KEY (`AccountID`) REFERENCES `Account` (`AccountID`),
  CONSTRAINT `ContractAccount_ContractID_89134db5_fk_Contract_ContractID` FOREIGN KEY (`ContractID`) REFERENCES `Contract` (`ContractID`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `ContractSeries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ContractSeries` (
  `SeriesID` int NOT NULL AUTO_INCREMENT,
  `SeriesName` varchar(100) NOT NULL,
  `SortOrder` int NOT NULL,
  PRIMARY KEY (`SeriesID`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `ContractSeriesMap`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ContractSeriesMap` (
  `id` int NOT NULL AUTO_INCREMENT,
  `contract_id` int NOT NULL,
  `contractseries_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ContractSeriesMap_contract_id_contractseries_id_78207abb_uniq` (`contract_id`,`contractseries_id`),
  KEY `ContractSeriesMap_contractseries_id_389a2229_fk_ContractS` (`contractseries_id`),
  CONSTRAINT `ContractSeriesMap_contract_id_20d5d280_fk_Contract_ContractID` FOREIGN KEY (`contract_id`) REFERENCES `Contract` (`ContractID`),
  CONSTRAINT `ContractSeriesMap_contractseries_id_389a2229_fk_ContractS` FOREIGN KEY (`contractseries_id`) REFERENCES `ContractSeries` (`SeriesID`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `CrewAssignment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `CrewAssignment` (
  `AssignmentID` int NOT NULL AUTO_INCREMENT,
  `StartDate` date NOT NULL,
  `EndDate` date DEFAULT NULL,
  `EmployeeID` int NOT NULL,
  `PositionID` int DEFAULT NULL,
  `ShifterID` int NOT NULL,
  PRIMARY KEY (`AssignmentID`),
  KEY `CrewAssignment_EmployeeID_935568f6_fk_Employee_EID` (`EmployeeID`),
  KEY `CrewAssignment_PositionID_0ffbf12f_fk_Position_PositionID` (`PositionID`),
  KEY `CrewAssignment_ShifterID_34596da7_fk_Employee_EID` (`ShifterID`),
  CONSTRAINT `CrewAssignment_EmployeeID_935568f6_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `CrewAssignment_PositionID_0ffbf12f_fk_Position_PositionID` FOREIGN KEY (`PositionID`) REFERENCES `Position` (`PositionID`),
  CONSTRAINT `CrewAssignment_ShifterID_34596da7_fk_Employee_EID` FOREIGN KEY (`ShifterID`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `CrewCoverage`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `CrewCoverage` (
  `CoverageID` int NOT NULL AUTO_INCREMENT,
  `StartDate` date NOT NULL,
  `EndDate` date DEFAULT NULL,
  `Notes` longtext,
  `AssignedAt` datetime(6) NOT NULL,
  `AssignedBy` int NOT NULL,
  `CoveringShifterID` int NOT NULL,
  `HomeShifterID` int NOT NULL,
  PRIMARY KEY (`CoverageID`),
  KEY `CrewCoverage_AssignedBy_d01d148a_fk_Employee_EID` (`AssignedBy`),
  KEY `CrewCoverage_CoveringShifterID_9abcc069_fk_Employee_EID` (`CoveringShifterID`),
  KEY `CrewCoverage_HomeShifterID_f7d98cf9_fk_Employee_EID` (`HomeShifterID`),
  CONSTRAINT `CrewCoverage_AssignedBy_d01d148a_fk_Employee_EID` FOREIGN KEY (`AssignedBy`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `CrewCoverage_CoveringShifterID_9abcc069_fk_Employee_EID` FOREIGN KEY (`CoveringShifterID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `CrewCoverage_HomeShifterID_f7d98cf9_fk_Employee_EID` FOREIGN KEY (`HomeShifterID`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Crews`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Crews` (
  `CrewID` int NOT NULL AUTO_INCREMENT,
  `CrewName` varchar(10) NOT NULL,
  `IsActive` int NOT NULL,
  PRIMARY KEY (`CrewID`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Department`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Department` (
  `DepartmentID` int NOT NULL AUTO_INCREMENT,
  `DepartmentName` varchar(255) NOT NULL,
  `IsActive` int NOT NULL,
  PRIMARY KEY (`DepartmentID`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Employee`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Employee` (
  `EID` int NOT NULL AUTO_INCREMENT,
  `EmployeeID` varchar(255) NOT NULL,
  `FirstName` varchar(100) NOT NULL,
  `LastName` varchar(100) NOT NULL,
  `Passpin` varchar(255) DEFAULT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `Email` varchar(255) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `PhoneNumber` varchar(20) NOT NULL,
  `is_temporary` tinyint(1) NOT NULL,
  `IsActive` tinyint(1) NOT NULL,
  `LastLogin` datetime(6) DEFAULT NULL,
  `LastResetDate` datetime(6) DEFAULT NULL,
  `ProfilePic` varchar(255) DEFAULT NULL,
  `MicrosoftID` varchar(255) DEFAULT NULL,
  `RoleID` int NOT NULL,
  `HasAccess` tinyint(1) NOT NULL,
  `ShifterType` varchar(20) DEFAULT NULL,
  `CrewID` int DEFAULT NULL,
  `AccountID` int DEFAULT NULL,
  `ContractID` int DEFAULT NULL,
  `EmploymentType` varchar(10) NOT NULL,
  `SupervisorID` int DEFAULT NULL,
  `HireDate` date DEFAULT NULL,
  `TerminationDate` date DEFAULT NULL,
  PRIMARY KEY (`EID`),
  UNIQUE KEY `EID` (`EID`),
  UNIQUE KEY `Employee_EmployeeID_uniq` (`EmployeeID`),
  UNIQUE KEY `Email` (`Email`),
  KEY `Employee_RoleID_d5ef358a_fk_Roles_RoleID` (`RoleID`),
  KEY `Employee_CrewID_d8053c78_fk_Crews_CrewID` (`CrewID`),
  KEY `Employee_AccountID_700c5b5c_fk_Account_AccountID` (`AccountID`),
  KEY `Employee_ContractID_36c3f8c4_fk_Contract_ContractID` (`ContractID`),
  KEY `Employee_SupervisorID_eid_fk` (`SupervisorID`),
  CONSTRAINT `Employee_AccountID_700c5b5c_fk_Account_AccountID` FOREIGN KEY (`AccountID`) REFERENCES `Account` (`AccountID`),
  CONSTRAINT `Employee_ContractID_36c3f8c4_fk_Contract_ContractID` FOREIGN KEY (`ContractID`) REFERENCES `Contract` (`ContractID`),
  CONSTRAINT `Employee_CrewID_d8053c78_fk_Crews_CrewID` FOREIGN KEY (`CrewID`) REFERENCES `Crews` (`CrewID`),
  CONSTRAINT `Employee_RoleID_d5ef358a_fk_Roles_RoleID` FOREIGN KEY (`RoleID`) REFERENCES `Roles` (`RoleID`),
  CONSTRAINT `Employee_SupervisorID_eid_fk` FOREIGN KEY (`SupervisorID`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=28 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `EmployeeBonus`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `EmployeeBonus` (
  `EmployeeBonusID` int NOT NULL AUTO_INCREMENT,
  `BonusType` varchar(10) NOT NULL,
  `PeriodStart` date NOT NULL,
  `PeriodEnd` date NOT NULL,
  `BonusRateCode` varchar(2) NOT NULL,
  `Notes` longtext,
  `AssignedAt` datetime(6) NOT NULL,
  `AppliedAtPayroll` datetime(6) DEFAULT NULL,
  `AppliedByPayroll` int DEFAULT NULL,
  `AssignedBy` int NOT NULL,
  `EmployeeID` int NOT NULL,
  PRIMARY KEY (`EmployeeBonusID`),
  KEY `EmployeeBonus_AppliedByPayroll_5b8ec28e_fk_Employee_EID` (`AppliedByPayroll`),
  KEY `EmployeeBonus_AssignedBy_2d921370_fk_Employee_EID` (`AssignedBy`),
  KEY `EmployeeBonus_EmployeeID_47ee017b_fk_Employee_EID` (`EmployeeID`),
  CONSTRAINT `EmployeeBonus_AppliedByPayroll_5b8ec28e_fk_Employee_EID` FOREIGN KEY (`AppliedByPayroll`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `EmployeeBonus_AssignedBy_2d921370_fk_Employee_EID` FOREIGN KEY (`AssignedBy`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `EmployeeBonus_EmployeeID_47ee017b_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Employee_groups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Employee_groups` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `group_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `Employee_groups_user_id_group_id_1de47afa_uniq` (`user_id`,`group_id`),
  KEY `Employee_groups_group_id_444bcb5e_fk_auth_group_id` (`group_id`),
  CONSTRAINT `Employee_groups_group_id_444bcb5e_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
  CONSTRAINT `Employee_groups_user_id_eid_fk` FOREIGN KEY (`user_id`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Employee_user_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Employee_user_permissions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `Employee_user_permissions_user_id_permission_id_bcce7528_uniq` (`user_id`,`permission_id`),
  KEY `Employee_user_permis_permission_id_15654f2d_fk_auth_perm` (`permission_id`),
  CONSTRAINT `Employee_user_permis_permission_id_15654f2d_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `Employee_user_permissions_user_id_eid_fk` FOREIGN KEY (`user_id`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `LeaveAllocation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `LeaveAllocation` (
  `AllocationID` int NOT NULL AUTO_INCREMENT,
  `Year` int NOT NULL,
  `AllocatedHours` decimal(5,2) NOT NULL,
  `IsProrated` int NOT NULL,
  `EmployeeID` int NOT NULL,
  `LeaveTypeID` int NOT NULL,
  PRIMARY KEY (`AllocationID`),
  KEY `LeaveAllocation_EmployeeID_df0c059e_fk_Employee_EID` (`EmployeeID`),
  KEY `LeaveAllocation_LeaveTypeID_17ba6541_fk_LeaveType_LeaveTypeID` (`LeaveTypeID`),
  CONSTRAINT `LeaveAllocation_EmployeeID_df0c059e_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `LeaveAllocation_LeaveTypeID_17ba6541_fk_LeaveType_LeaveTypeID` FOREIGN KEY (`LeaveTypeID`) REFERENCES `LeaveType` (`LeaveTypeID`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `LeaveType`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `LeaveType` (
  `LeaveTypeID` int NOT NULL AUTO_INCREMENT,
  `LeaveTypeName` varchar(255) NOT NULL,
  `IsActive` int NOT NULL,
  `IsPayable` tinyint(1) NOT NULL,
  PRIMARY KEY (`LeaveTypeID`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `LieuDayLedger`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `LieuDayLedger` (
  `LedgerID` int NOT NULL AUTO_INCREMENT,
  `Status` varchar(10) NOT NULL,
  `EarnedAt` datetime(6) NOT NULL,
  `UsedAt` datetime(6) DEFAULT NULL,
  `UsedEntryType` varchar(20) DEFAULT NULL,
  `UsedEntryID` int DEFAULT NULL,
  `EmployeeID` int NOT NULL,
  `StatHolidayID` int NOT NULL,
  PRIMARY KEY (`LedgerID`),
  UNIQUE KEY `LieuDayLedger_EmployeeID_StatHolidayID_27f1f6c3_uniq` (`EmployeeID`,`StatHolidayID`),
  KEY `LieuDayLedger_StatHolidayID_bd36ebdd_fk_StatHoliday_StatID` (`StatHolidayID`),
  CONSTRAINT `LieuDayLedger_EmployeeID_1f120cf9_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `LieuDayLedger_StatHolidayID_bd36ebdd_fk_StatHoliday_StatID` FOREIGN KEY (`StatHolidayID`) REFERENCES `StatHoliday` (`StatID`)
) ENGINE=InnoDB AUTO_INCREMENT=60 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `MainEntry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `MainEntry` (
  `MainEntryID` int NOT NULL AUTO_INCREMENT,
  `SAPWorkID` varchar(100) DEFAULT NULL,
  `ShiftType` varchar(5) NOT NULL,
  `HoursWorked` decimal(5,2) NOT NULL,
  `EntryDescription` longtext,
  `StartDate` date NOT NULL,
  `EndDate` date DEFAULT NULL,
  `LineStatus` varchar(15) NOT NULL,
  `ApprovedAt` datetime(6) DEFAULT NULL,
  `SupervisorNote` longtext,
  `ApprovedBy` int DEFAULT NULL,
  `LeaveTypeID` int DEFAULT NULL,
  `WorkCategoryID` int DEFAULT NULL,
  `WorkOrderID` int DEFAULT NULL,
  `MainHeaderID` int NOT NULL,
  PRIMARY KEY (`MainEntryID`),
  KEY `MainEntry_ApprovedBy_99b29a63_fk_Employee_EID` (`ApprovedBy`),
  KEY `MainEntry_LeaveTypeID_1b2dbd7b_fk_LeaveType_LeaveTypeID` (`LeaveTypeID`),
  KEY `MainEntry_WorkCategoryID_a22c2879_fk_WorkCategory_CategoryID` (`WorkCategoryID`),
  KEY `MainEntry_WorkOrderID_080fdaf0_fk_WorkOrderCache_WorkOrderID` (`WorkOrderID`),
  KEY `MainEntry_MainHeaderID_4264c287_fk_MainHeader_MainHeaderID` (`MainHeaderID`),
  CONSTRAINT `MainEntry_ApprovedBy_99b29a63_fk_Employee_EID` FOREIGN KEY (`ApprovedBy`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `MainEntry_LeaveTypeID_1b2dbd7b_fk_LeaveType_LeaveTypeID` FOREIGN KEY (`LeaveTypeID`) REFERENCES `LeaveType` (`LeaveTypeID`),
  CONSTRAINT `MainEntry_MainHeaderID_4264c287_fk_MainHeader_MainHeaderID` FOREIGN KEY (`MainHeaderID`) REFERENCES `MainHeader` (`MainHeaderID`),
  CONSTRAINT `MainEntry_WorkCategoryID_a22c2879_fk_WorkCategory_CategoryID` FOREIGN KEY (`WorkCategoryID`) REFERENCES `WorkCategory` (`CategoryID`),
  CONSTRAINT `MainEntry_WorkOrderID_080fdaf0_fk_WorkOrderCache_WorkOrderID` FOREIGN KEY (`WorkOrderID`) REFERENCES `WorkOrderCache` (`WorkOrderID`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `MainHeader`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `MainHeader` (
  `MainHeaderID` int NOT NULL AUTO_INCREMENT,
  `OverallStatus` varchar(25) NOT NULL,
  `StartedAt` datetime(6) NOT NULL,
  `SubmittedAt` datetime(6) DEFAULT NULL,
  `CompletedAt` datetime(6) DEFAULT NULL,
  `PaidAt` datetime(6) DEFAULT NULL,
  `CrewID` int DEFAULT NULL,
  `EmployeeID` int NOT NULL,
  `PaidBy` int DEFAULT NULL,
  PRIMARY KEY (`MainHeaderID`),
  KEY `MainHeader_CrewID_13eef4c5_fk_Crews_CrewID` (`CrewID`),
  KEY `MainHeader_EmployeeID_b90c4e95_fk_Employee_EID` (`EmployeeID`),
  KEY `MainHeader_PaidBy_05d40972_fk_Employee_EID` (`PaidBy`),
  CONSTRAINT `MainHeader_CrewID_13eef4c5_fk_Crews_CrewID` FOREIGN KEY (`CrewID`) REFERENCES `Crews` (`CrewID`),
  CONSTRAINT `MainHeader_EmployeeID_b90c4e95_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `MainHeader_PaidBy_05d40972_fk_Employee_EID` FOREIGN KEY (`PaidBy`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `OperationsBonus`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `OperationsBonus` (
  `OpsBonusID` int NOT NULL AUTO_INCREMENT,
  `BonusMonth` date NOT NULL,
  `BonusRateCode` varchar(2) NOT NULL,
  `Notes` longtext,
  `ReviewedAt` datetime(6) DEFAULT NULL,
  `AppliedAtPayroll` datetime(6) DEFAULT NULL,
  `Status` varchar(10) NOT NULL,
  `AppliedByPayroll` int DEFAULT NULL,
  `EmployeeID` int NOT NULL,
  `ReviewedBy` int DEFAULT NULL,
  PRIMARY KEY (`OpsBonusID`),
  UNIQUE KEY `OperationsBonus_EmployeeID_BonusMonth_6538f4df_uniq` (`EmployeeID`,`BonusMonth`),
  KEY `OperationsBonus_AppliedByPayroll_f378e6db_fk_Employee_EID` (`AppliedByPayroll`),
  KEY `OperationsBonus_ReviewedBy_2909c9de_fk_Employee_EID` (`ReviewedBy`),
  CONSTRAINT `OperationsBonus_AppliedByPayroll_f378e6db_fk_Employee_EID` FOREIGN KEY (`AppliedByPayroll`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `OperationsBonus_EmployeeID_48f7b153_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `OperationsBonus_ReviewedBy_2909c9de_fk_Employee_EID` FOREIGN KEY (`ReviewedBy`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `OperationsEntry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `OperationsEntry` (
  `OpsEntryID` int NOT NULL AUTO_INCREMENT,
  `HoursWorked` decimal(5,2) NOT NULL,
  `Remarks` longtext,
  `HauledTo` varchar(255) DEFAULT NULL,
  `TonnesOreHauled` decimal(8,2) DEFAULT NULL,
  `TonnesWasteHauled` decimal(8,2) DEFAULT NULL,
  `LowGradeHauled` decimal(8,2) DEFAULT NULL,
  `TonnesOreSkipped` decimal(8,2) DEFAULT NULL,
  `TonnesWasteSkipped` decimal(8,2) DEFAULT NULL,
  `LowGradeSkipped` decimal(8,2) DEFAULT NULL,
  `LongHoleFootage` decimal(8,2) DEFAULT NULL,
  `LineStatus` varchar(15) NOT NULL,
  `PaidAt` datetime(6) DEFAULT NULL,
  `ApprovedAt_Capt` datetime(6) DEFAULT NULL,
  `CaptainNote` longtext,
  `AccountID` int DEFAULT NULL,
  `ApprovedBy_Capt` int DEFAULT NULL,
  `ContractID` int NOT NULL,
  `EmployeeID` int NOT NULL,
  `PaidBy` int DEFAULT NULL,
  `OpsHeaderID` int NOT NULL,
  `LeaveTypeID` int DEFAULT NULL,
  `OpsCategoryID` int DEFAULT NULL,
  PRIMARY KEY (`OpsEntryID`),
  KEY `OperationsEntry_AccountID_9fdf1ec4_fk_Account_AccountID` (`AccountID`),
  KEY `OperationsEntry_ApprovedBy_Capt_8f8413c1_fk_Employee_EID` (`ApprovedBy_Capt`),
  KEY `OperationsEntry_ContractID_a02f8fc6_fk_Contract_ContractID` (`ContractID`),
  KEY `OperationsEntry_EmployeeID_c05fc645_fk_Employee_EID` (`EmployeeID`),
  KEY `OperationsEntry_PaidBy_04cf154f_fk_Employee_EID` (`PaidBy`),
  KEY `OperationsEntry_OpsHeaderID_9510cb55_fk_Operation` (`OpsHeaderID`),
  KEY `OperationsEntry_LeaveTypeID_5b84d689_fk_LeaveType_LeaveTypeID` (`LeaveTypeID`),
  KEY `OperationsEntry_OpsCategoryID_3c1edb8c_fk_OpsCategory_CategoryID` (`OpsCategoryID`),
  CONSTRAINT `OperationsEntry_AccountID_9fdf1ec4_fk_Account_AccountID` FOREIGN KEY (`AccountID`) REFERENCES `Account` (`AccountID`),
  CONSTRAINT `OperationsEntry_ApprovedBy_Capt_8f8413c1_fk_Employee_EID` FOREIGN KEY (`ApprovedBy_Capt`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `OperationsEntry_ContractID_a02f8fc6_fk_Contract_ContractID` FOREIGN KEY (`ContractID`) REFERENCES `Contract` (`ContractID`),
  CONSTRAINT `OperationsEntry_EmployeeID_c05fc645_fk_Employee_EID` FOREIGN KEY (`EmployeeID`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `OperationsEntry_LeaveTypeID_5b84d689_fk_LeaveType_LeaveTypeID` FOREIGN KEY (`LeaveTypeID`) REFERENCES `LeaveType` (`LeaveTypeID`),
  CONSTRAINT `OperationsEntry_OpsCategoryID_3c1edb8c_fk_OpsCategory_CategoryID` FOREIGN KEY (`OpsCategoryID`) REFERENCES `OpsCategory` (`CategoryID`),
  CONSTRAINT `OperationsEntry_OpsHeaderID_9510cb55_fk_Operation` FOREIGN KEY (`OpsHeaderID`) REFERENCES `OperationsHeader` (`OpsHeaderID`),
  CONSTRAINT `OperationsEntry_PaidBy_04cf154f_fk_Employee_EID` FOREIGN KEY (`PaidBy`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `OperationsHeader`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `OperationsHeader` (
  `OpsHeaderID` int NOT NULL AUTO_INCREMENT,
  `ShiftDate` date NOT NULL,
  `ShiftType` varchar(5) NOT NULL,
  `OverallStatus` varchar(25) NOT NULL,
  `StartedAt` datetime(6) NOT NULL,
  `SubmittedAt` datetime(6) DEFAULT NULL,
  `OHApprovedAt_Capt` datetime(6) DEFAULT NULL,
  `Section` varchar(20) DEFAULT NULL,
  `CoverageID` int DEFAULT NULL,
  `CrewID` int NOT NULL,
  `OpsHApprovedBy_Capt` int DEFAULT NULL,
  `ShifterID` int NOT NULL,
  PRIMARY KEY (`OpsHeaderID`),
  KEY `OperationsHeader_CoverageID_10a74347_fk_CrewCoverage_CoverageID` (`CoverageID`),
  KEY `OperationsHeader_CrewID_dc45421a_fk_Crews_CrewID` (`CrewID`),
  KEY `OperationsHeader_OpsHApprovedBy_Capt_48c00a05_fk_Employee_EID` (`OpsHApprovedBy_Capt`),
  KEY `OperationsHeader_ShifterID_ec8127b5_fk_Employee_EID` (`ShifterID`),
  CONSTRAINT `OperationsHeader_CoverageID_10a74347_fk_CrewCoverage_CoverageID` FOREIGN KEY (`CoverageID`) REFERENCES `CrewCoverage` (`CoverageID`),
  CONSTRAINT `OperationsHeader_CrewID_dc45421a_fk_Crews_CrewID` FOREIGN KEY (`CrewID`) REFERENCES `Crews` (`CrewID`),
  CONSTRAINT `OperationsHeader_OpsHApprovedBy_Capt_48c00a05_fk_Employee_EID` FOREIGN KEY (`OpsHApprovedBy_Capt`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `OperationsHeader_ShifterID_ec8127b5_fk_Employee_EID` FOREIGN KEY (`ShifterID`) REFERENCES `Employee` (`EID`)
) ENGINE=InnoDB AUTO_INCREMENT=31 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `OpsCategory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `OpsCategory` (
  `CategoryID` int NOT NULL AUTO_INCREMENT,
  `CategoryName` varchar(255) NOT NULL,
  `IsProductive` int NOT NULL,
  `IsActive` int NOT NULL,
  `IsPayable` tinyint(1) NOT NULL,
  PRIMARY KEY (`CategoryID`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Position`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Position` (
  `PositionID` int NOT NULL AUTO_INCREMENT,
  `PositionName` varchar(100) NOT NULL,
  `IsActive` int NOT NULL,
  PRIMARY KEY (`PositionID`)
) ENGINE=InnoDB AUTO_INCREMENT=49 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `Roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `Roles` (
  `RoleID` int NOT NULL AUTO_INCREMENT,
  `RoleName` varchar(100) NOT NULL,
  `IsUniqueAssignment` int DEFAULT NULL,
  `AccessID` int NOT NULL,
  `DepartmentID` int NOT NULL,
  `VacationHours` int DEFAULT NULL,
  `ShowsLeaveBalance` tinyint(1) NOT NULL,
  PRIMARY KEY (`RoleID`),
  KEY `Roles_AccessID_2a693674_fk_AccessLevel_AccessID` (`AccessID`),
  KEY `Roles_DepartmentID_dadd5cef_fk_Department_DepartmentID` (`DepartmentID`),
  CONSTRAINT `Roles_AccessID_2a693674_fk_AccessLevel_AccessID` FOREIGN KEY (`AccessID`) REFERENCES `AccessLevel` (`AccessID`),
  CONSTRAINT `Roles_DepartmentID_dadd5cef_fk_Department_DepartmentID` FOREIGN KEY (`DepartmentID`) REFERENCES `Department` (`DepartmentID`)
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `StatHoliday`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `StatHoliday` (
  `StatID` int NOT NULL AUTO_INCREMENT,
  `StatName` varchar(255) NOT NULL,
  `StatDate` date NOT NULL,
  `IsActive` int NOT NULL,
  `Province` varchar(2) DEFAULT NULL,
  PRIMARY KEY (`StatID`)
) ENGINE=InnoDB AUTO_INCREMENT=119 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `VacationRatePolicy`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `VacationRatePolicy` (
  `PolicyID` int NOT NULL AUTO_INCREMENT,
  `Bucket` varchar(20) NOT NULL,
  `EffectiveYear` int NOT NULL,
  `MonthlyRateHours` decimal(4,2) NOT NULL,
  PRIMARY KEY (`PolicyID`),
  UNIQUE KEY `VacationRatePolicy_Bucket_EffectiveYear_86d10d07_uniq` (`Bucket`,`EffectiveYear`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `WorkCategory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `WorkCategory` (
  `CategoryID` int NOT NULL AUTO_INCREMENT,
  `CategoryName` varchar(255) NOT NULL,
  `IsProductive` int NOT NULL,
  `IsActive` int NOT NULL,
  `IsPayable` tinyint(1) NOT NULL,
  PRIMARY KEY (`CategoryID`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `WorkOrderCache`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `WorkOrderCache` (
  `WorkOrderID` int NOT NULL AUTO_INCREMENT,
  `SAP_WorkOrder` varchar(255) DEFAULT NULL,
  `Description` varchar(255) DEFAULT NULL,
  `FunctionalGroup` varchar(255) DEFAULT NULL,
  `SAP_StartDate` date NOT NULL,
  `SAP_CompletionDate` date DEFAULT NULL,
  PRIMARY KEY (`WorkOrderID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `auth_group`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_group` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(150) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `auth_group_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_group_permissions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `group_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `auth_permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_permission` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `content_type_id` int NOT NULL,
  `codename` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=141 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `django_admin_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_admin_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `action_time` datetime(6) NOT NULL,
  `object_id` longtext,
  `object_repr` varchar(200) NOT NULL,
  `action_flag` smallint unsigned NOT NULL,
  `change_message` longtext NOT NULL,
  `content_type_id` int DEFAULT NULL,
  `user_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `django_admin_log_content_type_id_c4bce8eb_fk_django_co` (`content_type_id`),
  KEY `django_admin_log_user_id_eid_fk` (`user_id`),
  CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`),
  CONSTRAINT `django_admin_log_user_id_eid_fk` FOREIGN KEY (`user_id`) REFERENCES `Employee` (`EID`),
  CONSTRAINT `django_admin_log_chk_1` CHECK ((`action_flag` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `django_content_type`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_content_type` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) NOT NULL,
  `model` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`)
) ENGINE=InnoDB AUTO_INCREMENT=36 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `django_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_migrations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=66 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `django_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_session` (
  `session_key` varchar(40) NOT NULL,
  `session_data` longtext NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`),
  KEY `django_session_expire_date_a5c62663` (`expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

