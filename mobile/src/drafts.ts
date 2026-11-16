import AsyncStorage from '@react-native-async-storage/async-storage';
import { createDraftStore } from './draftStorage';
export const draftStore = (origin: string, email: string) => createDraftStore(AsyncStorage, origin, email);
