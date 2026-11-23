// 화면이 데이터를 읽고 쓰는 곳은 여기 한 곳이다 (스탠드얼론 ② Task 1, 설계 6.3절).
// 어느 구현을 쓸지는 edition.js 가 정한다 - 일반 버전은 data-firebase.js(Firebase), 스탠드얼론은 data-local.js(이 PC 의 로컬 서버).
// 구현은 반드시 동적 import 로 불러온다 - 정적으로 부르면 스탠드얼론 웹에도 Firebase SDK·프로젝트 주소가 실린다.
// 화면 모듈은 data-firebase.js·data-local.js 를 직접 부르지 않고 이 파일만 부른다.
import { EDITION, TEST_BUILD } from "./edition.js";

const impl = await import(EDITION === "standalone" ? "./data-local.js" : "./data-firebase.js");

export { EDITION, TEST_BUILD };   // TEST_BUILD: 스탠드얼론 시험용 빌드 (app.js 가 맨 위 띠를 그린다)
export const {
  init, onSession, signIn, signOut, signedIn, sessionUid, handoffFailed, changePassword, emailFor,
  getCompany, watch, skewReady, skewMs, pushCommand, saveSettings,
  listRuns, getWallet, watchWallet, sumRuns,
  // 스탠드얼론에만 있는 것 (일반 버전은 undefined): 서버 미사용 시계 되돌리기, 계정 관리 (관리자)
  touch, listAccounts, addAccount, updateAccount, removeAccount,
  // 휴대폰 (스탠드얼론 관리자, 계획 ④) - 일반 버전은 undefined
  listPhones, startPhonePair, phonePairState, cancelPhonePair, updatePhone, removePhone,
} = impl;
