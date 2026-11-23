import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    title: 'Chat | AlphaDesk',
    loadComponent: () => import('./chat/chat-page').then((module) => module.ChatPage),
  },
];
