%drift.size = type i64
%DriftString = type { %drift.size, i8* }
%DriftError = type { i64, %DriftString, i8*, %drift.size, i8*, %drift.size }
%FnResult_Int_Error = type { i1, i64, %DriftError* }
%DriftDiagnosticValue = type { i8, [7 x i8], [2 x i64] }
%DriftOptionalInt = type { i8, i64 }
%DriftOptionalBool = type { i8, i8 }
%DriftOptionalString = type { i8, %DriftString }
%DriftArrayHeader = type { i64, i64, i8* }
%FnResult_Void_Error = type { i1, i8, %DriftError* }
%FnResult_String_Error = type { i1, %DriftString, %DriftError* }

@.str0 = private unnamed_addr constant [1 x i8] c"\00"
@.str1 = private unnamed_addr constant [7 x i8] c"m:Boom\00"
@.str2 = private unnamed_addr constant [3 x i8] c"hi\00"
@.str3 = private unnamed_addr constant [2 x i8] c"a\00"
@.str4 = private unnamed_addr constant [2 x i8] c"b\00"
@.str5 = private unnamed_addr constant [2 x i8] c"a\00"
@.str6 = private unnamed_addr constant [2 x i8] c"b\00"
@.str7 = private unnamed_addr constant [1 x i8] c"\00"

declare void @__exc_attrs_get_dv(%DriftDiagnosticValue*, %DriftError*, %DriftString)
declare %DriftDiagnosticValue @drift_dv_missing()
declare %DriftDiagnosticValue @drift_dv_int(i64)
declare %DriftDiagnosticValue @drift_dv_bool(i1)
declare %DriftDiagnosticValue @drift_dv_string(%DriftString)
declare %DriftOptionalInt @drift_dv_as_int(%DriftDiagnosticValue*)
declare %DriftOptionalBool @drift_dv_as_bool(%DriftDiagnosticValue*)
declare %DriftOptionalString @drift_dv_as_string(%DriftDiagnosticValue*)

declare %DriftError* @drift_error_new(i64, %DriftString)
declare %DriftError* @drift_error_new_with_payload(i64, %DriftString, %DriftString, %DriftDiagnosticValue)
declare void @drift_error_add_attr_dv(%DriftError*, %DriftString, %DriftDiagnosticValue*)

define i64 @handle() {
entry:
  %strptr1 = getelementptr inbounds [1 x i8], [1 x i8]* @.str0, i32 0, i32 0
  %str02 = insertvalue %DriftString undef, %drift.size 0, 0
  %t1 = insertvalue %DriftString %str02, i8* %strptr1, 1
  br label %try_body
try_body:
  %t3 = add i64 0, 1460523783985996615
  %strptr3 = getelementptr inbounds [7 x i8], [7 x i8]* @.str1, i32 0, i32 0
  %str04 = insertvalue %DriftString undef, %drift.size 6, 0
  %t5 = insertvalue %DriftString %str04, i8* %strptr3, 1
  %t6 = add i64 0, 7
  %t7 = call %DriftDiagnosticValue @drift_dv_int(i64 %t6)
  %strptr5 = getelementptr inbounds [3 x i8], [3 x i8]* @.str2, i32 0, i32 0
  %str06 = insertvalue %DriftString undef, %drift.size 2, 0
  %t8 = insertvalue %DriftString %str06, i8* %strptr5, 1
  %t9 = call %DriftDiagnosticValue @drift_dv_string(%DriftString %t8)
  %strptr7 = getelementptr inbounds [2 x i8], [2 x i8]* @.str3, i32 0, i32 0
  %str08 = insertvalue %DriftString undef, %drift.size 1, 0
  %t10 = insertvalue %DriftString %str08, i8* %strptr7, 1
  %t4 = call %DriftError* @drift_error_new_with_payload(i64 %t3, %DriftString %t5, %DriftString %t10, %DriftDiagnosticValue %t7)
  %strptr9 = getelementptr inbounds [2 x i8], [2 x i8]* @.str4, i32 0, i32 0
  %str010 = insertvalue %DriftString undef, %drift.size 1, 0
  %t11 = insertvalue %DriftString %str010, i8* %strptr9, 1
  %dvptr11 = alloca %DriftDiagnosticValue
  store %DriftDiagnosticValue %t9, %DriftDiagnosticValue* %dvptr11
  call void @drift_error_add_attr_dv(%DriftError* %t4, %DriftString %t11, %DriftDiagnosticValue* %dvptr11)
  br label %try_dispatch
try_dispatch:
  %err_val12 = load %DriftError, %DriftError* %t4
  %t13 = extractvalue %DriftError %err_val12, 0
  %t14 = add i64 0, 1460523783985996615
  %t15 = icmp eq i64 %t13, %t14
  br i1 %t15, label %try_catch_0, label %try_dispatch_next
try_dispatch_next:
  %t16 = add i64 0, 0
  ret i64 %t16
try_catch_0:
  %err_val13 = load %DriftError, %DriftError* %t4
  %t18 = extractvalue %DriftError %err_val13, 0
  %strptr14 = getelementptr inbounds [2 x i8], [2 x i8]* @.str5, i32 0, i32 0
  %str015 = insertvalue %DriftString undef, %drift.size 1, 0
  %t20 = insertvalue %DriftString %str015, i8* %strptr14, 1
  %dvptr16 = alloca %DriftDiagnosticValue
  call void @__exc_attrs_get_dv(%DriftDiagnosticValue* %dvptr16, %DriftError* %t4, %DriftString %t20)
  %t21 = load %DriftDiagnosticValue, %DriftDiagnosticValue* %dvptr16
  %dvarg17 = alloca %DriftDiagnosticValue
  store %DriftDiagnosticValue %t21, %DriftDiagnosticValue* %dvarg17
  %t23 = call %DriftOptionalInt @drift_dv_as_int(%DriftDiagnosticValue* %dvarg17)
  %strptr18 = getelementptr inbounds [2 x i8], [2 x i8]* @.str6, i32 0, i32 0
  %str019 = insertvalue %DriftString undef, %drift.size 1, 0
  %t25 = insertvalue %DriftString %str019, i8* %strptr18, 1
  %dvptr20 = alloca %DriftDiagnosticValue
  call void @__exc_attrs_get_dv(%DriftDiagnosticValue* %dvptr20, %DriftError* %t4, %DriftString %t25)
  %t26 = load %DriftDiagnosticValue, %DriftDiagnosticValue* %dvptr20
  %dvarg21 = alloca %DriftDiagnosticValue
  store %DriftDiagnosticValue %t26, %DriftDiagnosticValue* %dvarg21
  %t28 = call %DriftOptionalString @drift_dv_as_string(%DriftDiagnosticValue* %dvarg21)
  %t29 = add i64 0, 0
  ret i64 %t29
try_cont:
  %t30 = add i64 0, 1
  ret i64 %t30
}
define i64 @main() {
entry:
  %strptr1 = getelementptr inbounds [1 x i8], [1 x i8]* @.str7, i32 0, i32 0
  %str02 = insertvalue %DriftString undef, %drift.size 0, 0
  %t1 = insertvalue %DriftString %str02, i8* %strptr1, 1
  %t2 = call i64 @handle()
  %t3 = add i64 0, 0
  ret i64 %t3
}
