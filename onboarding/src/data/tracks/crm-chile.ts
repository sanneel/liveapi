import type { Track } from '../types'
import { journeyNameMatchesConvention } from '../brands'

// Steps are deliberately small. If a lesson needs more than about three short
// paragraphs, it gets split — a long screen is a failed screen here.
const track: Track = {
  id: 'crm-chile-v1',
  name: 'CRM Chile — Foundations',
  description: 'Player Journeys, the node types, and your first hands-on campaign.',

  steps: [
    // ── 0 · say hello before anything else ──────────────────────────────────
    {
      id: 'lesson-welcome',
      chapter: 'Welcome',
      type: 'lesson',
      eyebrow: 'Welcome',
      title: 'Welcome onboard.',
      flick: {
        pose: 'teach',
        say: 'Hi, I am Flick. I will walk you through it, one screen at a time. Nothing you do in here touches anything real.',
      },
      content: [
        {
          kind: 'paragraph',
          html: 'I am going to explain some <strong>standards of our CRM</strong>, so you know how we use them. Here is the order.',
        },
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'First, some standard promotions.',
              sub: 'What the player flow looks like from their side, and then how we track it from ours.',
            },
            {
              text: 'Then the important nodes.',
              sub: 'What rules they have and how to use them, plus how our journeys are set up and why those particular nodes.',
            },
            {
              text: 'Then a playground.',
              sub: 'Tasks you can build freely. Nothing there can damage anything, it is only there to build your knowledge.',
            },
          ],
        },
      ],
    },

    // ── Promotion walkthroughs ───────────────────────────────────────────────
    //
    // One template, repeated per promotion, so the shape is learned once:
    //
    //   1 OFFER    how a player finds it        · where the object lives for us
    //   2 INSIDE   what opens when they tap     · how it is configured
    //   3 ACTION   what pressing the button did · the record it wrote
    //   4 CHOICE   only if the promo asks       · the flows behind the options
    //   5 HELD     what they end up holding     · that player's journey log
    //
    // Every screen is the same two photos in the same order, player then ours.
    // Files: public/shots/<promo>/<n>-<beat>-<player|ours>.png
    {
      id: 'lesson-how-to-read',
      chapter: 'How to read this',
      tip: 'Left is always the player. Right is always us.',
      type: 'lesson',
      eyebrow: 'Before we start',
      title: 'Two views of the same moment.',
      content: [
        {
          kind: 'paragraph',
          html: 'Every screen from here shows one moment twice. On the <strong>left</strong> is what the player sees on the site. On the <strong>right</strong> is what that same moment looks like to us in the backoffice. Same second, two windows.',
        },
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'We walk one promotion at a time.',
              sub: 'How it is found, what opens, what the button does, and what the player is left holding. Then the next promotion, in the same order.',
            },
            {
              text: 'Nothing here is a mock-up.',
              sub: 'Every photo is a real capture of a real campaign with a real player in it, so the ids and the numbers can be traced across screens.',
            },
            {
              text: 'Click any photo to open it full size.',
              sub: 'The tables and logs are readable that way. Back and Continue are always at the bottom.',
            },
          ],
        },
      ],
    },

    {
      id: 'wheel-1-offer',
      chapter: 'Promotion · Fortune Wheel',
      tip: 'Every promotion the player sees is an object we own and can open.',
      type: 'lesson',
      eyebrow: 'Fortune Wheel · 1 of 5',
      title: 'Casino Wheel of Fortune.',
      flick: {
        pose: 'inspect',
        say: 'This one was live on the day the screenshots were taken, so everything you are about to see really happened.',
      },
      content: [
        {
          kind: 'paragraph',
          html: 'Now I will show you the <strong>Casino Wheel of Fortune</strong>. It was active on the day I captured these screenshots. On the left is where the player meets it. On the right is the same thing as an object we own.',
        },
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/wheel/1-offer-player.png',
              alt: 'The Bonificaciones list on the site with a Casino card reading Gira la Rueda de la Fortuna ahora, counting down 15H 48M, beside sports promos.',
              caption: 'THE PLAYER. The promotions page, with the wheel among the live promos.',
              marks: [{ x: 0.25, y: 0.47, label: 'Wheel of Fortune', from: 'left' }],
            },
            {
              src: 'shots/wheel/1-offer-ours.png',
              alt: 'The backoffice Promo list filtered to Active, showing randomizer RND-0-17731 named JBCL|CS|WOF|07.08.26.',
              caption: 'OUR SIDE. The same promotion in the Promo list.',
              marks: [{ x: 0.27, y: 0.42, label: 'Our RND', from: 'left' }],
            },
          ],
        },
      ],
    },

    {
      id: 'wheel-2-inside',
      chapter: 'Promotion · Fortune Wheel',
      tip: 'A prize is never a bonus. It is always a JRN.',
      type: 'lesson',
      eyebrow: 'Fortune Wheel · 2 of 5',
      title: 'Four prizes, twelve places.',
      flick: {
        pose: 'work',
        say: 'This is the part people get wrong at first, so take your time with the right-hand photo.',
      },
      content: [
        {
          kind: 'paragraph',
          html: 'The wheel has <strong>four different prizes</strong>, and each one sits on the wheel <strong>three times</strong>, which is why you count twelve wedges. We set the percentages, and the machine calculates which prize the player gets when they spin.',
        },
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/wheel/2-inside-player.png',
              alt: 'The Rueda de la fortuna page: a twelve wedge wheel showing 50 GG con depósito, 50 GG sin depósito, Bonos de depósito and Jackpot 200 FS, with a Spin button.',
              caption: 'THE PLAYER. Twelve wedges, four prizes, no odds shown.',
            },
            {
              src: 'shots/wheel/2-inside-ours.png',
              alt: 'The randomizer prize table: four rows, each a JRN journey id against a probability of 55, 42, 2.7 and 0.3, with a greyed out Add prize button.',
              caption: 'OUR SIDE. Four rows. A JRN id, and the odds of landing on it.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'Now the important part. <strong>A prize cannot just be free spins, or money, or anything else.</strong> Every prize is a <strong>JRN, a journey</strong>, and each of those journeys starts with an <strong>API entry source</strong>. That is how the wheel hands a winner over: it adds the player into the journey through that entry. All four prizes on this wheel are JRNs.',
        },
        {
          kind: 'table',
          rows: [
            { node: 'JRN-0-572381', role: '50 free spins, deposit linked', detail: '55%' },
            { node: 'JRN-0-572307', role: 'Deposit bonuses', detail: '42%' },
            { node: 'JRN-0-423152', role: '50 free spins, no deposit', detail: '2.7%' },
            { node: 'JRN-0-572386', role: '50 free spins, no deposit', detail: '0.3%' },
          ],
        },
        {
          kind: 'paragraph',
          html: 'Which fixes the build order: the journeys exist first, because this table can only point at JRNs that already exist. The weights must total 100, and <em>Add prize</em> is greyed out because the number of slices comes from the template.',
        },
      ],
    },

    {
      id: 'wheel-3-action',
      chapter: 'Promotion · Fortune Wheel',
      tip: 'The players list is how you prove a spin happened and where it went.',
      type: 'lesson',
      eyebrow: 'Fortune Wheel · 3 of 5',
      title: 'He spun, and we can prove it.',
      content: [
        {
          kind: 'paragraph',
          html: 'The player spun the wheel and won the <strong>deposit linked free spins</strong>. From our side we can check that he actually spun, and <strong>which JRN id he won</strong>, so winners are traceable.',
        },
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/wheel/3-action-player.png',
              alt: 'A Tu recompensa dialog over the wheel, confetti around a 50 GG CON DEPÓSITO badge, saying the bonus will activate automatically.',
              caption: 'THE PLAYER. Tu recompensa. 50 GG con depósito, the 55% prize.',
            },
            {
              src: 'shots/wheel/3-action-ours.png',
              alt: 'The randomizer players list showing one account, added 16:09, activated 16:09, claimed 16:10, with bonus campaign JRN-0-572381.',
              caption: 'OUR SIDE. Who spun, when they claimed, and the JRN they won.',
              marks: [{ x: 0.66, y: 0.27, label: 'The JRN he won', from: 'right' }],
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'Once the player is added into that journey he can go straight to the promotions page. And what does he see there? <strong>Several options to choose from.</strong> That is exactly the <strong>Multipurpose Promotion</strong> we created inside the journey, which is the next screen.',
        },
      ],
    },

    {
      id: 'wheel-4-choice',
      chapter: 'Promotion · Fortune Wheel',
      tip: 'Choosing adds the player to one promotion id, not to all three.',
      type: 'lesson',
      eyebrow: 'Fortune Wheel · 4 of 5',
      title: 'One promotion holding three.',
      flick: {
        pose: 'lead',
        say: 'Follow the arrow first, then read down the three columns. Same shape three times.',
      },
      content: [
        {
          kind: 'paragraph',
          html: 'This journey has one big <strong>Multipurpose Promotion</strong> which includes <strong>three promotions</strong>. So how does the flow work?',
        },
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/wheel/4-choice-player.png',
              alt: 'A promotion screen with ID 672079 headed Selecciona 1 de los 3 bonos, offering 50 free spins at $200, $100 and $1,000 bet, each with Seleccionar and Detalles.',
              caption: 'THE PLAYER. Selecciona 1 de los 3 bonos. Three bets: $200, $100, $1,000.',
            },
            {
              src: 'shots/wheel/4-choice-ours.png',
              alt: 'The journey canvas showing a Multipurpose Promotion node offered within 1 day, Accepted 17678 below it, branching into Flow 1, Flow 2 and Flow 3 named 15k dep, 10k dep and big, each with its own deposit gate, Casino FreeSpin and Casino bonus.',
              caption: 'OUR SIDE. The Multipurpose Promotion, and the three flows under it.',
              marks: [{ x: 0.62, y: 0.075, label: 'The Multipurpose Promotion', from: 'right' }],
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'The player <strong>chooses one promotion</strong> and is added into <strong>that promotion id</strong>. So on his promotions page a new <em>chosen</em> promotion appears, with its own terms, and only the flow behind it runs. The other two never start for him.',
        },
        {
          kind: 'paragraph',
          html: 'The counts show how it split in practice: 17 678 accepted the offer, then 8 252 took 15k dep, 6 766 took 10k dep and 2 660 took big.',
        },
      ],
    },

    {
      id: 'wheel-5-held',
      chapter: 'Promotion · Fortune Wheel',
      tip: 'Two clocks, started at different moments. Beating one is not beating both.',
      type: 'lesson',
      eyebrow: 'Fortune Wheel · 5 of 5',
      title: 'What they end up holding.',
      content: [
        {
          kind: 'paragraph',
          html: 'The end of the promotion for the player is a single card with terms on it. The end for us is a log we can read back.',
        },
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/wheel/5-held-player.png',
              alt: 'The Bonificaciones page showing ACTIVA 1 and one card, 50 Giros Gratis Apuesta $200, with 15000 CLP minimum deposit, a Depósito button and 23H 59M remaining.',
              caption: 'THE PLAYER. One active bonus, 15.000 CLP minimum deposit, and a clock.',
            },
            {
              src: 'shots/wheel/5-held-ours.png',
              alt: 'The Journey log for that player: deposit activated, 15k dep promotion accepted in Flow 1, Multipurpose Promotion accepted then offered, a decision split, and API player added to journey.',
              caption: 'OUR SIDE. Six events for that one player. Newest first, so read upward.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'The terms came with the option they chose, not with the chooser: 15.000 CLP. A second clock also started, one to accept and a separate one to deposit.',
        },
        {
          kind: 'paragraph',
          html: 'The log is where you go when someone says they did not get their bonus. Read upward: added by API, split, offered, accepted, the real offer accepted inside <strong>Flow 1</strong>, deposit gate armed one second later.',
        },
      ],
    },

    // ── Template to copy for the next promotion ─────────────────────────────
    //
    // Fill these three, add a CHOICE screen only if the promotion asks the player
    // to pick, and drop the files at public/shots/promo-2/. Delete this chapter if
    // it is still empty when the course goes to a real trainee.
    {
      id: 'promo2-1-offer',
      chapter: 'Promotion · next',
      type: 'lesson',
      eyebrow: 'Next promotion · 1 of 3',
      title: 'How a player finds it.',
      content: [
        {
          kind: 'paragraph',
          html: 'Same template as the wheel: where the player meets this promotion, and where it lives for us.',
        },
        {
          kind: 'shots',
          items: [
            { src: 'shots/promo-2/1-offer-player.png', alt: 'How the player finds this promotion.', caption: 'THE PLAYER. Where they meet it.' },
            { src: 'shots/promo-2/1-offer-ours.png', alt: 'The same promotion as an object in the backoffice.', caption: 'OUR SIDE. The object we own.' },
          ],
        },
      ],
    },

    {
      id: 'promo2-2-inside',
      chapter: 'Promotion · next',
      type: 'lesson',
      eyebrow: 'Next promotion · 2 of 3',
      title: 'What opens when they tap.',
      content: [
        {
          kind: 'paragraph',
          html: 'What the player actually plays or reads, and the configuration behind it.',
        },
        {
          kind: 'shots',
          items: [
            { src: 'shots/promo-2/2-inside-player.png', alt: 'What opens for the player.', caption: 'THE PLAYER. What opens.' },
            { src: 'shots/promo-2/2-inside-ours.png', alt: 'How that is configured on our side.', caption: 'OUR SIDE. How it is set up.' },
          ],
        },
      ],
    },

    {
      id: 'promo2-3-after',
      chapter: 'Promotion · next',
      type: 'lesson',
      eyebrow: 'Next promotion · 3 of 3',
      title: 'What the button did.',
      content: [
        {
          kind: 'paragraph',
          html: 'What the player is left with, and the record it wrote for us.',
        },
        {
          kind: 'shots',
          items: [
            { src: 'shots/promo-2/3-after-player.png', alt: 'What the player ends up with.', caption: 'THE PLAYER. What they hold.' },
            { src: 'shots/promo-2/3-after-ours.png', alt: 'The record on our side.', caption: 'OUR SIDE. The record it wrote.' },
          ],
        },
      ],
    },

    // ── What was true in every one of them ───────────────────────────────────
    {
      id: 'lesson-what-repeats',
      chapter: 'What repeats',
      tip: 'These four hold for every promotion, not just the wheel.',
      type: 'lesson',
      eyebrow: 'Across every promotion',
      title: 'Four things that were true every time.',
      content: [
        {
          kind: 'paragraph',
          html: 'Different promotions, same skeleton. Whatever you are handed next, these four hold.',
        },
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'A promotion node awards nothing.',
              sub: 'It is the surface a player opts in on, or picks from. The condition and reward nodes behind it are the journey. A flow that stops at the promotion is a button wired to nothing.',
            },
            {
              text: 'A prize is a probability and a journey.',
              sub: 'Wheels and scratch cards do not award anything themselves. They add the winner to a JRN, which is where the real work sits. So the journeys are built first.',
            },
            {
              text: 'A chooser sits in front of a promotion, never instead of one.',
              sub: 'Every flow needs its own promotion inside it. That inner one carries the terms and is what the reward depends on.',
            },
            {
              text: 'Clocks are per step, not per campaign.',
              sub: 'Accepting an offer and satisfying a deposit have separate windows that start at different moments. Check both before you promise a player anything.',
            },
          ],
        },
      ],
    },

    // ── 1 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-what-is',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'The idea',
      title: 'Player Journeys is a decision engine.',
      content: [
        {
          kind: 'paragraph',
          html: 'A <strong>journey</strong> watches what players do and answers on its own — no operator presses anything. It listens for an action, applies your logic, and hands out a reward or a message.',
        },
        {
          kind: 'diagram',
          boxes: [
            {
              id: 'event',
              label: 'Player action',
              examples: ['Registers', 'Makes a deposit', 'Goes quiet for 14 days'],
            },
            {
              id: 'journey',
              label: 'Journey',
              examples: ['Waits', 'Conditions', 'Branches'],
            },
            {
              id: 'action',
              label: 'Response',
              examples: ['Free spins', 'Deposit bonus', 'Notification'],
            },
          ],
          arrows: [
            { from: 'event', to: 'journey' },
            { from: 'journey', to: 'action' },
          ],
        },
      ],
    },

    // ── 2 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-timeline',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'How it runs',
      title: 'Every player runs on their own clock.',
      content: [
        {
          kind: 'paragraph',
          html: 'Once published, a journey runs continuously. Each qualifying player enters at the top and moves along their own timeline, independent of everyone else.',
        },
        {
          kind: 'paragraph',
          html: 'So a one-hour wait means one hour <em>after that player arrived</em> — not one hour after you hit publish. Two players who enter a day apart are simply at different points of the same journey.',
        },
      ],
    },

    // ── 3 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-where',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'Where it lives',
      title: 'Journey builder is the list of everything running.',
      content: [
        {
          kind: 'paragraph',
          html: 'Every journey the team has ever built sits here — running, planned, terminated. You will spend most of your time on this screen.',
        },
        {
          kind: 'screen',
          name: 'journeys-list',
          caption:
            'Note the names. The brand code opens every one, so the list can be scanned by brand without opening anything.',
        },
      ],
    },

    // ── 4 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-promo',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'What we create',
      title: 'Three things. Not nine.',
      content: [
        {
          kind: 'paragraph',
          html: 'The Promo section offers nine mechanics. In Chile we use two of them — <strong>Promo Page</strong> and <strong>Prediction</strong> — plus the <strong>Journey builder</strong> behind both. Ignore the rest until someone asks for it.',
        },
        {
          kind: 'screen',
          name: 'promo-list',
          caption: 'The two we create are marked. Everything else on that menu is someone else’s market.',
        },
      ],
    },

    // ── 5 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-nodes',
      chapter: 'The blocks',
      type: 'lesson',
      eyebrow: 'The blocks',
      title: 'Six blocks. The whole language.',
      content: [
        {
          kind: 'paragraph',
          html: 'Every journey — simple or elaborate — is assembled from the same six node types. Learn these and you can read any journey on the canvas.',
        },
        {
          kind: 'table',
          rows: [
            { node: 'Entry Source', role: 'Decides who enters the journey' },
            { node: 'Wait', role: 'Holds the player until the right moment' },
            { node: 'Condition', role: 'Asks whether the player did the thing' },
            { node: 'Reward', role: 'Credits a bonus automatically' },
            { node: 'Communication', role: 'Sends a message on one channel' },
            { node: 'Exit', role: 'Ends that player’s journey' },
          ],
        },
      ],
    },

    // ── 4 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-rules-shape',
      chapter: 'The rules',
      type: 'lesson',
      eyebrow: 'Rules — shape',
      title: 'Three rules about shape.',
      content: [
        {
          kind: 'paragraph',
          html: 'These are not preferences. A journey that breaks one of them fails to save, or runs quietly wrong.',
        },
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'Every journey starts with exactly one Entry Source.',
              sub: 'It is the door a Promo Page points at. You cannot have two, and you cannot swap it after launch without updating the page.',
            },
            {
              text: 'Every node must connect to the next one.',
              sub: 'There is no implicit “carry on”. An unconnected node is a dead end, and the player stops there.',
            },
            {
              text: 'Every path must end in an Exit.',
              sub: 'Including the path for players who did not qualify. Without one they stay active in the journey and count in its audience forever.',
            },
          ],
        },
      ],
    },

    // ── 5 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-rules-behaviour',
      chapter: 'The rules',
      type: 'lesson',
      eyebrow: 'Rules — behaviour',
      title: 'Three rules about behaviour.',
      content: [
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'Waits pause. They do not branch.',
              sub: 'A Wait has one way forward: the clock runs out. It decides nothing.',
            },
            {
              text: 'Conditions branch — connect every outcome.',
              sub: 'A Deposit Condition has three: deposited, did not deposit, offer expired. All three need somewhere to go, even if two go straight to an Exit.',
            },
            {
              text: 'Save your change in both places.',
              sub: 'A journey lives twice — the visual canvas and the settings behind it. An edit saved to only one of them ships the wrong content with no warning.',
            },
          ],
        },
      ],
    },

    // ── 6 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-promo-vs-journey',
      chapter: 'Distinctions',
      type: 'lesson',
      eyebrow: 'A distinction',
      title: 'A promotion is not a journey.',
      content: [
        {
          kind: 'paragraph',
          html: 'This is the most common mix-up. A <strong>promotion</strong> is what the player receives. A <strong>journey</strong> is what decides whether they receive it, when, and on what terms.',
        },
        {
          kind: 'split-card',
          left: {
            heading: 'Promotion',
            title: '50 Free Spins',
            body: 'What the player gets. Configured in the Promotions section, with its own name, display rules and reward details. The journey points at it — it does not contain it.',
          },
          right: {
            heading: 'Journey',
            title: 'First Deposit Flow',
            body: 'How the player gets it. Register → wait 1h → check deposit → grant spins → notify. The reward node inside references the promotion by name.',
          },
        },
        {
          kind: 'paragraph',
          html: 'The same promotion can be used by several journeys. Updating its details never means touching them.',
        },
      ],
    },

    // ── 6b ──────────────────────────────────────────────────────────────────
    {
      id: 'lesson-connection',
      chapter: 'Distinctions',
      type: 'lesson',
      eyebrow: 'The wiring',
      title: 'One field connects the two.',
      content: [
        {
          kind: 'paragraph',
          html: 'Building a promo page ends on this screen. Brand, currency, the URLs the player will land on — and then <strong>Journey Builder connection</strong>, where you pick the Journey ID.',
        },
        {
          kind: 'screen',
          name: 'promo-page-form',
          caption:
            'That dropdown is the whole link between a promotion and its automation. Pick the wrong journey here and the page pays out somebody else’s campaign.',
        },
        {
          kind: 'paragraph',
          html: 'Which is why the journey is named <strong>JBCL | CS | RB - Game of the week | 50 FS</strong> and not “test 3”. You are choosing it from a list of eighteen hundred.',
        },
      ],
    },

    // ── 6c ──────────────────────────────────────────────────────────────────
    {
      id: 'lesson-player-side',
      chapter: 'Distinctions',
      type: 'lesson',
      eyebrow: 'The player’s side',
      title: 'The button is the door.',
      content: [
        {
          kind: 'paragraph',
          html: 'Everything you connect shows up under <strong>Promociones</strong> on the site. Each card here is a promo page you built.',
        },
        {
          kind: 'screen',
          name: 'promotions-site',
          caption:
            'Juega Ahora, Participate — whatever the button says, pressing it is the moment the player enters the journey you attached.',
        },
        {
          kind: 'paragraph',
          html: 'So nothing runs until someone taps. The journey does not go looking for players; the promo page delivers them, one press at a time, each starting their own clock.',
        },
      ],
    },

    // ── 7 ───────────────────────────────────────────────────────────────────
    {
      id: 'showcase-gotw',
      chapter: 'A real campaign',
      type: 'showcase',
      eyebrow: 'One real campaign',
      title: 'Game of the Week, set up.',
      description:
        'One campaign, built from the three things you just met. Open any step to see what we actually create.',
      items: [
        {
          id: 'sc-page',
          label: 'Promo Page — the thing the player opens',
          description:
            'Created from Promo → Create new → Promo Page. It carries the match artwork, the terms, and the button. It is also the door: opening it is what puts a player into the journey.',
        },
        {
          id: 'sc-prediction',
          label: 'Prediction — the mechanic, when the match needs one',
          description:
            'Created from Promo → Create new → Prediction. Game of the Week can run without it, but when we ask players to call a scoreline this is the object that collects and settles the answers.',
        },
        {
          id: 'sc-journey',
          label: 'Journey builder — the automation behind both',
          description:
            'Created from Journey builder → Create new, named JBCL | Game of the Week 06.08. The promo objects are what the player sees; the journey is what decides and pays.',
        },
        {
          id: 'sc-source',
          label: 'Entry Source — from the Promo Page',
          description:
            'Players enter when they open the match Promo Page. The source registers them and starts their personal clock.',
        },
        {
          id: 'sc-cond',
          label: 'Deposit Condition — $10,000 CLP minimum, 48h window',
          description:
            'The journey checks for a deposit of at least $10,000 CLP within 48 hours of entry. Deposited goes to the reward; did not goes to an exit.',
        },
        {
          id: 'sc-reward',
          label: 'Reward — 20% deposit match, capped at $50,000 CLP',
          description:
            'Credited automatically; the player claims nothing. Amount, cap and wagering requirement are all set inside the node.',
        },
        {
          id: 'sc-comms',
          label: 'Communication — “Your bonus is ready”',
          description:
            'Sent once the bonus is credited. It references a Content Studio template and lands in the player’s notification bell.',
        },
        {
          id: 'sc-exit',
          label: 'Exit — on both paths',
          description:
            'Two exits: one after the notification, one straight off the condition for players who never deposited. Both have to exist.',
        },
      ],
    },

    // ── 8 ───────────────────────────────────────────────────────────────────
    {
      id: 'task-journey-settings',
      chapter: 'Build it',
      type: 'task',
      eyebrow: 'Your turn',
      title: 'Set the journey up.',
      brief:
        'A welcome journey for Chile casino players. It should start the moment it is published, and stop accepting new players on 07.08. Work in any order — the checks tell you where you are.',

      replica: {
        id: 'journey-settings-replica',
        screen: 'journey-settings',
        screenTitle: 'New Journey',
        screenSubtitle: 'General settings',
      },

      checks: [
        {
          id: 'c-brand',
          label: 'Brand is JBCL',
          test: ctx => ctx.fields.brand === 'JBCL',
        },
        {
          id: 'c-name',
          label: 'Title follows the naming convention',
          test: ctx =>
            journeyNameMatchesConvention(ctx.fields['journey-title'] ?? '', ctx.fields.brand),
        },
        {
          id: 'c-start',
          label: 'Starts immediately after publish',
          test: ctx => ctx.fields['start-immediately'] === 'true',
        },
        {
          id: 'c-entry',
          label: 'Entry closes on 07.08',
          test: ctx => ctx.fields['entry-until'] === '2026-08-07',
        },
        {
          id: 'c-product',
          label: 'Product type is Casino',
          test: ctx => ctx.fields['product-type'] === 'casino',
        },
        {
          id: 'c-purpose',
          label: 'Purpose is Marketing - Welcome',
          test: ctx => ctx.fields.purpose === 'marketing-welcome',
        },
      ],
    },

    // ── 9 ───────────────────────────────────────────────────────────────────
    {
      id: 'task-journey-builder',
      chapter: 'Build it',
      type: 'task',
      eyebrow: 'Your turn',
      title: 'Build the flow.',
      brief:
        'Now assemble it. Players come in from a segment, we wait, we check they deposited, we pay a casino reward, and we tell them. Drag activities from the palette onto the canvas — drop between two nodes to insert, drag a node to reorder, and click one to add it without dragging.',

      replica: {
        id: 'journey-builder-replica',
        screen: 'journey-builder',
        screenTitle: 'Journey builder',
      },

      checks: [
        {
          id: 'b-source',
          label: 'Starts with an input source',
          test: ctx => ctx.canvas[0] === 'act-custom-segment',
        },
        {
          id: 'b-wait',
          label: 'Has a Wait',
          test: ctx => ctx.canvas.includes('act-wait'),
        },
        {
          id: 'b-deposit',
          label: 'Has a Deposit condition',
          test: ctx => ctx.canvas.includes('act-deposit'),
        },
        {
          id: 'b-reward',
          label: 'Pays a casino reward',
          test: ctx =>
            ctx.canvas.includes('act-casino-freespin') || ctx.canvas.includes('act-casino-bonus'),
        },
        {
          id: 'b-comms',
          label: 'Tells the player something',
          test: ctx =>
            ['act-email', 'act-sms', 'act-native-push', 'act-onsite-messaging'].some(id =>
              ctx.canvas.includes(id),
            ),
        },
        {
          id: 'b-order',
          label: 'Condition comes before the reward',
          test: ctx => {
            const cond = ctx.canvas.indexOf('act-deposit')
            const reward = Math.max(
              ctx.canvas.indexOf('act-casino-freespin'),
              ctx.canvas.indexOf('act-casino-bonus'),
            )
            return cond !== -1 && reward !== -1 && cond < reward
          },
        },
      ],
    },

    // ── 10 ──────────────────────────────────────────────────────────────────
    {
      id: 'task-gotw',
      chapter: 'Build it',
      type: 'task',
      eyebrow: 'Your turn',
      title: 'Fill the campaign.',
      brief:
        'Game of the Week for Colo-Colo vs Concepción this weekend: a 20% deposit match, connected to the standard GotW journey. Save it as a draft when the form is right.',

      replica: {
        id: 'gotw-replica',
        screenTitle: 'New Campaign',
        screenSubtitle: 'Game of the Week',
        panels: [
          { id: 'campaign-details', title: 'Campaign details' },
          { id: 'featured-event', title: 'Featured event' },
          { id: 'reward-config', title: 'Reward' },
          { id: 'journey-link', title: 'Journey' },
        ],
        elements: [
          {
            id: 'campaign-name',
            type: 'input',
            panel: 'campaign-details',
            label: 'Campaign name',
            placeholder: 'e.g. GotW — Colo-Colo vs Concepción',
          },
          {
            id: 'campaign-type',
            type: 'select',
            panel: 'campaign-details',
            label: 'Campaign type',
            defaultValue: '',
            options: [
              { value: '', label: 'Select type…' },
              { value: 'welcome', label: 'Welcome' },
              { value: 'gotw', label: 'Game of the Week' },
              { value: 'reactivation', label: 'Reactivation' },
              { value: 'vip', label: 'VIP upgrade' },
            ],
          },
          {
            id: 'active-from',
            type: 'input',
            panel: 'campaign-details',
            label: 'Active from',
            defaultValue: '2026-08-07',
            readonly: true,
          },
          {
            id: 'active-to',
            type: 'input',
            panel: 'campaign-details',
            label: 'Active to',
            defaultValue: '2026-08-08',
            readonly: true,
          },

          {
            id: 'sport',
            type: 'select',
            panel: 'featured-event',
            label: 'Sport',
            defaultValue: '',
            options: [
              { value: '', label: 'Select sport…' },
              { value: 'football', label: 'Football' },
              { value: 'tennis', label: 'Tennis' },
              { value: 'basketball', label: 'Basketball' },
            ],
          },
          {
            id: 'match',
            type: 'select',
            panel: 'featured-event',
            label: 'Match',
            defaultValue: '',
            options: [
              { value: '', label: 'Select match…' },
              { value: 'colo-concep', label: 'Colo-Colo vs Concepción' },
              { value: 'uc-huachipato', label: 'U. Católica vs Huachipato' },
              { value: 'liverpool-chelsea', label: 'Liverpool vs Chelsea' },
            ],
          },

          {
            id: 'bonus-type',
            type: 'select',
            panel: 'reward-config',
            label: 'Bonus type',
            defaultValue: '',
            options: [
              { value: '', label: 'Select bonus type…' },
              { value: 'freespins', label: 'Free spins' },
              { value: 'deposit-match', label: 'Deposit match (%)' },
              { value: 'freebet', label: 'Free bet' },
            ],
          },
          {
            id: 'bonus-pct',
            type: 'input',
            panel: 'reward-config',
            label: 'Bonus percentage (%)',
            placeholder: 'e.g. 20',
          },
          {
            id: 'min-deposit',
            type: 'input',
            panel: 'reward-config',
            label: 'Minimum deposit (CLP)',
            placeholder: 'e.g. 10000',
          },
          {
            id: 'max-bonus',
            type: 'input',
            panel: 'reward-config',
            label: 'Maximum bonus (CLP)',
            placeholder: 'e.g. 50000',
          },

          {
            id: 'journey-select',
            type: 'select',
            panel: 'journey-link',
            label: 'Journey to connect',
            defaultValue: '',
            options: [
              { value: '', label: 'Select journey…' },
              { value: 'first-deposit', label: 'First Deposit Flow' },
              { value: 'gotw-standard', label: 'GotW — standard deposit' },
              { value: 'reactivation', label: 'Reactivation 14 days' },
            ],
          },

          { id: 'btn-save', type: 'button', label: 'Save draft', variant: 'secondary' },
          { id: 'btn-publish', type: 'button', label: 'Publish campaign', variant: 'primary' },
        ],
      },

      checks: [
        {
          id: 'g-name',
          label: 'Campaign is named',
          test: ctx => (ctx.fields['campaign-name'] ?? '').trim().length > 3,
        },
        {
          id: 'g-type',
          label: 'Type is Game of the Week',
          test: ctx => ctx.fields['campaign-type'] === 'gotw',
        },
        {
          id: 'g-match',
          label: 'Colo-Colo vs Concepción is the featured match',
          test: ctx => ctx.fields.sport === 'football' && ctx.fields.match === 'colo-concep',
        },
        {
          id: 'g-bonus',
          label: 'A 20% deposit match',
          test: ctx =>
            ctx.fields['bonus-type'] === 'deposit-match' &&
            (ctx.fields['bonus-pct'] ?? '').trim() === '20',
        },
        {
          id: 'g-journey',
          label: 'Connected to the GotW journey',
          test: ctx => ctx.fields['journey-select'] === 'gotw-standard',
        },
        {
          id: 'g-saved',
          label: 'Saved as a draft',
          test: ctx => ctx.fields['btn-save'] === 'pressed',
        },
      ],
    },
  ],
}

export default track
